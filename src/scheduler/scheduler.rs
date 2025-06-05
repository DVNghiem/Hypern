use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use chrono::Utc;
use chrono_tz::Tz;
use std::thread;
use cron::Schedule;
use std::str::FromStr;

use crate::instants::get_runtime;
use super::retry::RetryPolicy;
use super::job::{Job, JobType};

#[pyclass(subclass)]
pub struct Scheduler {
    jobs: Arc<Mutex<HashMap<String, Job>>>,
    is_running: Arc<Mutex<bool>>,
    completed_jobs: Arc<Mutex<HashSet<String>>>,
}

#[pymethods]
impl Scheduler {
    #[new]
    pub fn new() -> PyResult<Self> {
        Ok(Scheduler {
            jobs: Arc::new(Mutex::new(HashMap::new())),
            is_running: Arc::new(Mutex::new(false)),
            completed_jobs: Arc::new(Mutex::new(HashSet::new())),
        })
    }

    #[pyo3(signature = (job_type, schedule_param, task, timezone, dependencies, retry_policy=None))]
    pub fn add_job(
        &self,
        py: Python<'_>,
        job_type: &str,
        schedule_param: &str, // interval in seconds for interval jobs, cron expression for cron jobs
        task: PyObject,
        timezone: &str,
        dependencies: Vec<String>,
        retry_policy: Option<(u32, u64, bool)>, // (max_retries, retry_delay_secs, exponential_backoff)
    ) -> PyResult<String> {
        if !task.as_ref().is_callable() {
            return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>("Task must be callable"));
        }

        // Parse timezone
        let tz: Tz = timezone.parse().map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid timezone: {}", e))
        })?;

        // Create JobType
        let job_type = match job_type {
            "interval" => {
                let secs = schedule_param.parse::<u64>().map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid interval: {}", e))
                })?;
                JobType::INTERVAL(Duration::from_secs(secs))
            },
            "cron" => {
                Schedule::from_str(schedule_param).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid cron expression: {} - {}", e, schedule_param))
                })?;
                JobType::CRON(schedule_param.to_string())
            },
            _ => return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid job type. Must be 'interval' or 'cron'")),
        };

        // Create retry policy if specified
        let retry_policy = retry_policy.map(|(max_retries, retry_delay_secs, exponential_backoff)| {
            RetryPolicy::new(max_retries, retry_delay_secs, exponential_backoff)
        });

        let job = Job::new(
            job_type,
            task,
            tz,
            dependencies.into_iter().collect(),
            retry_policy,
        );

        let job_id = job.get_id();
        self.jobs.lock().unwrap().insert(job_id.clone(), job);
        
        Ok(job_id)
    }

    pub fn remove_job(&self, id: &str) -> PyResult<()> {
        self.jobs.lock().unwrap().remove(id);
        Ok(())
    }

    pub fn start(&self) -> PyResult<()> {
        let mut is_running = self.is_running.lock().unwrap();
        if *is_running {
            return Ok(());
        }
        *is_running = true;
        drop(is_running);

        let jobs = Arc::clone(&self.jobs);
        let is_running = Arc::clone(&self.is_running);
        let runtime = get_runtime();
        let completed_jobs = Arc::clone(&self.completed_jobs);

        thread::spawn(move || {
            runtime.block_on(async {
                while *is_running.lock().unwrap() {
                    Python::with_gil(|py| {
                        let mut jobs_guard = jobs.lock().unwrap();
                        let completed_jobs_guard = completed_jobs.lock().unwrap();
                        let now = Utc::now();

                        for job in jobs_guard.values_mut() {
                            if job.should_run(now, &completed_jobs_guard) {
                                let result = job.get_task().call0(py);
                                job.set_last_run(now);

                                match result {
                                    Ok(_) => {
                                        job.set_last_success(now);
                                        job.set_next_retry(None);
                                        if let Some(policy) = &mut job.get_retry_policy() {
                                            policy.set_current_retry(0);
                                        }
                                    },
                                    Err(_e) => {
                                        if let Some(policy) = &mut job.get_retry_policy() {
                                            if policy.get_current_retry() < policy.get_max_retries() {
                                                let delay = policy.get_next_retry_delay();
                                                job.set_next_retry(Some(now + chrono::Duration::from_std(delay).unwrap()));
                                                policy.increase_current_retry();
                                            } else {
                                                job.set_next_retry(None);
                                                job.get_failed_dependencies().iter().for_each(|dep| {
                                                    completed_jobs.lock().unwrap().remove(dep);
                                                });
                                            }
                                        } else {
                                            job.set_next_retry(None);
                                        }
                                    }
                                }
                            }
                        }
                    });
                    
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            });
        });

        Ok(())
    }

    pub fn stop(&self) -> PyResult<()> {
        let mut is_running = self.is_running.lock().unwrap();
        *is_running = false;
        Ok(())
    }

    pub fn get_job_status(&self, id: &str) -> PyResult<Option<(f64, f64, Vec<String>, u32)>> {
        let jobs = self.jobs.lock().unwrap();
        if let Some(job) = jobs.get(id) {
            Ok(Some((
                job.get_last_run().map_or(0.0, |dt| dt.timestamp() as f64),
                job.get_last_success().map_or(0.0, |dt| dt.timestamp() as f64),
                job.get_failed_dependencies().iter().cloned().collect(),
                job.get_retry_policy().as_ref().map_or(0, |p| p.get_current_retry()),
            )))
        } else {
            Ok(None)
        }
    }

    pub fn get_next_run(&self, id: &str) -> PyResult<Option<f64>> {
        let jobs = self.jobs.lock().unwrap();
        if let Some(job) = jobs.get(id) {
            let now = Utc::now();
            
            // Check retry schedule first
            if let Some(next_retry) = job.get_next_retry() {
                return Ok(Some(next_retry.timestamp() as f64));
            }

            match &job.get_job_type() {
                JobType::INTERVAL(duration) => {
                    let next_run = match job.get_last_run() {
                        Some(last_run) => last_run + chrono::Duration::from_std(*duration).unwrap(),
                        None => now,
                    };
                    Ok(Some(next_run.timestamp() as f64))
                },
                JobType::CRON(expression) => {
                    let schedule = Schedule::from_str(expression).unwrap();
                    let local_now = now.with_timezone(&job.get_timezone());
                    let next_run = schedule.after(&local_now).next();
                    match next_run {
                        Some(next) => Ok(Some(next.timestamp() as f64)),
                        None => Ok(None),
                    }
                }
            }
        } else {
            Ok(None)
        }
    }
}
