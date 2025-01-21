use crate::router::route::Route;
use pyo3::prelude::*;
use std::collections::HashMap;

#[derive(Debug)]
#[pyclass]
#[derive(Clone)]
pub struct RadixNode {
    pub path: String,
    pub children: HashMap<char, RadixNode>,
    pub is_endpoint: bool,
    pub routes: HashMap<String, Route>,
    pub param_name: Option<String>,
}

impl Default for RadixNode {
    fn default() -> Self {
        Self::new()
    }
}
impl RadixNode {
    pub fn new() -> Self {
        Self {
            path: String::new(),
            children: HashMap::new(),
            is_endpoint: false,
            routes: HashMap::new(),
            param_name: None,
        }
    }

    pub fn insert(&mut self, path: &str, route: Route) {
        // Normalize the path first
        let normalized_path = if path == "/" {
            String::new()
        } else {
            path.trim_end_matches('/').to_string()
        };

        // For root path or empty path after normalization
        if normalized_path.is_empty() {
            self.is_endpoint = true;
            self.routes.insert(route.method.to_uppercase(), route);
            return;
        }

        let segments: Vec<&str> = normalized_path.split('/')
            .filter(|s| !s.is_empty())
            .collect();
        
        self._insert_segments(&segments, 0, route);
    }

    fn _insert_segments(&mut self, segments: &[&str], index: usize, route: Route) {
        if index >= segments.len() {
            self.is_endpoint = true;
            self.routes.insert(route.method.to_uppercase(), route);
            return;
        }

        let segment = segments[index];
        
        // For parameter segments
        if segment.starts_with(':') {
            let param_name = segment[1..].to_string();
            let param_node = self.children
                .entry(':')
                .or_insert_with(|| {
                    let mut node = RadixNode::new();
                    node.param_name = Some(param_name.clone());
                    node
                });
            param_node._insert_segments(segments, index + 1, route);
            return;
        }

        // For static segments
        let first_char = segment.chars().next().unwrap();
        let node = self.children
            .entry(first_char)
            .or_insert_with(|| {
                let mut node = RadixNode::new();
                node.path = segment.to_string();
                node
            });

        if node.path == segment {
            node._insert_segments(segments, index + 1, route);
        } else {
            // Create new node for different path
            let mut new_node = RadixNode::new();
            new_node.path = segment.to_string();
            new_node._insert_segments(segments, index + 1, route);
            self.children.insert(first_char, new_node);
        }
    }

    pub fn find(&self, path: &str, method: &str) -> Option<(&Route, HashMap<String, String>)> {
        let normalized_path = if path == "/" {
            String::new()
        } else {
            path.trim_end_matches('/').to_string()
        };

        let mut params = HashMap::new();
        if normalized_path.is_empty() {
            return if self.is_endpoint {
                self.routes.get(&method.to_uppercase()).map(|r| (r, params))
            } else {
                None
            };
        }

        let segments: Vec<&str> = normalized_path.split('/')
            .filter(|s| !s.is_empty())
            .collect();

        self._find_segments(&segments, 0, method, &mut params)
    }

    fn _find_segments<'a>(
        &'a self,
        segments: &[&str],
        index: usize,
        method: &str,
        params: &mut HashMap<String, String>,
    ) -> Option<(&'a Route, HashMap<String, String>)> {
        if index >= segments.len() {
            return if self.is_endpoint {
                self.routes.get(&method.to_uppercase()).map(|r| (r, params.clone()))
            } else {
                None
            };
        }

        let segment = segments[index];

        // Try exact static match first
        for (_, child) in self.children.iter() {
            if child.path == segment {
                if let Some(result) = child._find_segments(segments, index + 1, method, params) {
                    return Some(result);
                }
            }
        }

        // Try parameter match
        if let Some(param_node) = self.children.get(&':') {
            if let Some(param_name) = &param_node.param_name {
                params.insert(param_name.clone(), segment.to_string());
                if let Some(result) = param_node._find_segments(segments, index + 1, method, params) {
                    return Some(result);
                }
                params.remove(param_name);
            }
        }

        None
    }
}