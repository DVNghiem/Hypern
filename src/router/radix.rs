use crate::router::route::Route;
use pyo3::prelude::*;
use std::collections::HashMap;

#[pyclass]
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

impl Clone for RadixNode {
    fn clone(&self) -> Self {
        Self {
            path: self.path.clone(),
            children: self.children.clone(),
            is_endpoint: self.is_endpoint,
            routes: self.routes.clone(),
            param_name: self.param_name.clone(),
        }
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

    fn find_common_prefix(a: &str, b: &str) -> String {
        a.chars()
            .zip(b.chars())
            .take_while(|(ac, bc)| ac == bc)
            .map(|(c, _)| c)
            .collect()
    }

    pub fn insert(&mut self, path: &str, route: Route) {
        let normalized_path = if path == "/" {
            String::new()
        } else {
            path.trim_end_matches('/').to_string()
        };

        if normalized_path.is_empty() {
            self.is_endpoint = true;
            self.routes.insert(route.method.to_uppercase(), route);
            return;
        }

        let segments: Vec<&str> = normalized_path
            .split('/')
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

        if segment.starts_with(':') {
            let param_name = segment[1..].to_string();
            let param_node = self.children.entry(':').or_insert_with(|| {
                let mut node = RadixNode::new();
                node.param_name = Some(param_name.clone());
                node
            });
            param_node._insert_segments(segments, index + 1, route);
            return;
        }

        let first_char = match segment.chars().next() {
            Some(c) => c,
            None => return, // Empty segment, shouldn't happen due to normalization
        };

        if let Some(existing_node) = self.children.get_mut(&first_char) {
            let common_prefix = Self::find_common_prefix(&existing_node.path, segment);

            if common_prefix == existing_node.path {
                // Full match of existing node's path, check remaining segment
                let remaining = &segment[common_prefix.len()..];
                if remaining.is_empty() {
                    // Exact match, proceed to next segment
                    existing_node._insert_segments(segments, index + 1, route);
                } else {
                    // Split remaining part and insert
                    let mut new_node = RadixNode::new();
                    new_node.path = remaining.to_string();
                    new_node._insert_segments(segments, index + 1, route);
                    existing_node
                        .children
                        .entry(remaining.chars().next().unwrap())
                        .or_insert(new_node);
                }
            } else if !common_prefix.is_empty() {
                // Split existing node and insert new path
                let existing_remaining = existing_node.path[common_prefix.len()..].to_string();
                let new_remaining = segment[common_prefix.len()..].to_string();

                // Create new parent node with common prefix
                let mut new_parent = RadixNode::new();
                new_parent.path = common_prefix;

                // Modify existing node to hold remaining path
                let mut existing_child = RadixNode::new();
                existing_child.path = existing_remaining;
                existing_child.children = existing_node.children.clone();
                existing_child.is_endpoint = existing_node.is_endpoint;
                existing_child.routes = existing_node.routes.clone();
                existing_child.param_name = existing_node.param_name.clone();

                // Create new node for the new remaining path
                let mut new_child = RadixNode::new();
                new_child.path = new_remaining;
                new_child._insert_segments(segments, index + 1, route);

                // Attach children to new parent
                if let Some(c) = existing_child.path.chars().next() {
                    new_parent.children.insert(c, existing_child);
                }
                if let Some(c) = new_child.path.chars().next() {
                    new_parent.children.insert(c, new_child);
                }

                // Replace existing node with new parent
                *existing_node = new_parent;
            } else {
                // No common prefix, create new sibling node
                let mut new_node = RadixNode::new();
                new_node.path = segment.to_string();
                new_node._insert_segments(segments, index + 1, route);
                self.children.insert(first_char, new_node);
            }
        } else {
            // No existing node, create new
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

        let segments: Vec<&str> = normalized_path
            .split('/')
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
                self.routes
                    .get(&method.to_uppercase())
                    .map(|r| (r, params.clone()))
            } else {
                None
            };
        }

        let segment = segments[index];

        // Check static nodes
        if let Some(first_char) = segment.chars().next() {
            if let Some(child) = self.children.get(&first_char) {
                if let Some(remaining) = segment.strip_prefix(&child.path) {
                    if remaining.is_empty() {
                        // Full match, proceed to next segment
                        if let Some(result) =
                            child._find_segments(segments, index + 1, method, params)
                        {
                            return Some(result);
                        }
                    } else {
                        // Check if remaining part matches any child
                        if let Some(result) = child._find_segments(&[remaining], 0, method, params)
                        {
                            return Some(result);
                        }
                    }
                }
            }
        }

        // Check parameter node
        if let Some(param_node) = self.children.get(&':') {
            if let Some(param_name) = &param_node.param_name {
                params.insert(param_name.clone(), segment.to_string());
                if let Some(result) = param_node._find_segments(segments, index + 1, method, params)
                {
                    return Some(result);
                }
                params.remove(param_name);
            }
        }

        None
    }
}
