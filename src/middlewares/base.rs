use pyo3::prelude::*;

use crate::types::function_info::FunctionInfo;

#[pyclass]
#[derive(Clone)]
pub struct MiddlewareConfig {
    #[pyo3(get)]
    pub priority: i32,

    #[pyo3(get)]
    pub is_conditional: bool,
}

#[pymethods]
impl MiddlewareConfig {
    #[new]
    pub fn new(priority: i32, is_conditional: bool) -> Self {
        Self {
            priority,
            is_conditional,
        }
    }

    #[staticmethod]
    pub fn default() -> Self {
        Self {
            priority: 0,
            is_conditional: true,
        }
    }
}

#[derive(Clone)]
pub struct Middleware {
    before_hooks: Vec<(FunctionInfo, MiddlewareConfig)>,
    after_hooks: Vec<(FunctionInfo, MiddlewareConfig)>,
}

impl Middleware {
    pub fn new() -> Self {
        Self {
            before_hooks: Vec::new(),
            after_hooks: Vec::new(),
        }
    }

    pub fn add_before_hook(&mut self, hook: FunctionInfo, config: MiddlewareConfig) {
        self.before_hooks.push((hook, config));
        self.sort_hooks();
    }

    pub fn add_after_hook(&mut self, hook: FunctionInfo, config: MiddlewareConfig) {
        self.after_hooks.push((hook, config));
        self.sort_hooks();
    }

    fn sort_hooks(&mut self) {
        // Sort by priority (higher priority executes first)
        self.before_hooks
            .sort_by(|a, b| b.1.priority.cmp(&a.1.priority));
        self.after_hooks
            .sort_by(|a, b| b.1.priority.cmp(&a.1.priority));
    }

    pub fn get_before_hooks(&self) -> Vec<(FunctionInfo, MiddlewareConfig)> {
        self.before_hooks.clone()
    }

    pub fn get_after_hooks(&self) -> Vec<(FunctionInfo, MiddlewareConfig)> {
        self.after_hooks.clone()
    }

    pub fn set_before_hooks(&mut self, hooks: Vec<(FunctionInfo, MiddlewareConfig)>) {
        self.before_hooks = hooks;
        self.sort_hooks();
    }

    pub fn set_after_hooks(&mut self, hooks: Vec<(FunctionInfo, MiddlewareConfig)>) {
        self.after_hooks = hooks;
        self.sort_hooks();
    }
}
