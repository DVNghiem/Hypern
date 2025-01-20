use crate::router::route::Route;
use pyo3::prelude::*;
use std::collections::HashMap;

#[derive(Debug)]
#[pyclass]
#[derive(Clone)]
pub struct RadixNode {
    // Part of the path this node represents
    path: String,
    // Whether this node represents a complete path
    is_endpoint: bool,
    // Store routes indexed by HTTP method
    routes: HashMap<String, Route>,
    // Child nodes indexed by their first character
    children: HashMap<char, RadixNode>,
    // Parameter name if this is a parameter node (e.g., :id)
    param_name: Option<String>,
}

impl Default for RadixNode {
    fn default() -> Self {
        Self::new()
    }
}

impl RadixNode {
    pub fn new() -> Self {
        RadixNode {
            path: String::new(),
            is_endpoint: false,
            routes: HashMap::new(),
            children: HashMap::new(),
            param_name: None,
        }
    }

    pub fn insert(&mut self, path: &str, route: Route) {
        if path.is_empty() {
            self.is_endpoint = true;
            self.routes.insert(route.method.clone(), route);
            return;
        }

        let path_chars: Vec<char> = path.chars().collect();
        let current_pos = 0;

        // Handle path parameters
        if path_chars[0] == ':' {
            let param_end = path_chars
                .iter()
                .position(|&c| c == '/' || c == '?')
                .unwrap_or(path_chars.len());

            let param_name = path[1..param_end].to_string();
            let remaining_path = &path[param_end..];

            self.param_name = Some(param_name);
            if !remaining_path.is_empty() {
                self.insert(remaining_path, route);
            } else {
                self.is_endpoint = true;
                self.routes.insert(route.method.clone(), route);
            }
            return;
        }

        // Find matching prefix
        while current_pos < path_chars.len() {
            let c = path_chars[current_pos];
            if let Some(child) = self.children.get_mut(&c) {
                let mut i = 0;
                while i < child.path.len()
                    && current_pos + i < path_chars.len()
                    && child.path.chars().nth(i) == Some(path_chars[current_pos + i])
                {
                    i += 1;
                }

                if i < child.path.len() {
                    // Split existing node
                    let mut new_node = RadixNode::new();
                    new_node.path = child.path[i..].to_string();
                    new_node.children = std::mem::take(&mut child.children);
                    new_node.is_endpoint = child.is_endpoint;
                    new_node.routes = std::mem::take(&mut child.routes);

                    child.path = child.path[..i].to_string();
                    child
                        .children
                        .insert(new_node.path.chars().next().unwrap(), new_node);
                    child.is_endpoint = false;
                }

                if current_pos + i < path_chars.len() {
                    // Insert remaining path
                    let remaining = &path[current_pos + i..];
                    child.insert(remaining, route);
                } else {
                    // Path complete
                    child.is_endpoint = true;
                    child.routes.insert(route.method.clone(), route);
                }
                return;
            }

            // Create new node
            let mut node = RadixNode::new();
            node.path = path[current_pos..].to_string();
            node.is_endpoint = true;
            node.routes.insert(route.method.clone(), route);
            self.children.insert(path_chars[current_pos], node);
            return;
        }
    }

    pub fn find(&self, path: &str, method: &str) -> Option<(&Route, HashMap<String, String>)> {
        let mut params = HashMap::new();
        self._find(path, method, &mut params)
    }

    fn _find<'a>(
        &'a self,
        path: &str,
        method: &str,
        params: &mut HashMap<String, String>,
    ) -> Option<(&'a Route, HashMap<String, String>)> {
        if path.is_empty() {
            return if self.is_endpoint {
                self.routes.get(method).map(|route| (route, params.clone()))
            } else {
                None
            };
        }

        let path_chars: Vec<char> = path.chars().collect();

        // Handle parameter nodes
        if let Some(param_name) = &self.param_name {
            let param_end = path_chars
                .iter()
                .position(|&c| c == '/' || c == '?')
                .unwrap_or(path_chars.len());

            let param_value = &path[..param_end];
            params.insert(param_name.clone(), param_value.to_string());

            let remaining_path = &path[param_end..];
            if remaining_path.is_empty() && self.is_endpoint {
                return self.routes.get(method).map(|route| (route, params.clone()));
            }

            for child in self.children.values() {
                if let Some(result) = child._find(remaining_path, method, params) {
                    return Some(result);
                }
            }
        }

        // Regular path matching
        let first_char = path_chars[0];
        if let Some(child) = self.children.get(&first_char) {
            let mut i = 0;
            while i < child.path.len()
                && i < path.len()
                && child.path.chars().nth(i) == path.chars().nth(i)
            {
                i += 1;
            }

            if i == child.path.len() {
                return child._find(&path[i..], method, params);
            }
        }
        None
    }
}