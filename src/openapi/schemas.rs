use pyo3::{prelude::*, types::PyDict};
use regex::Regex;
use serde_json::Value;
use yaml_rust::Yaml;
use yaml_rust::YamlLoader;

fn yaml_to_json(yaml: &Yaml) -> Value {
    match yaml {
        Yaml::Real(s) | Yaml::String(s) => Value::String(s.clone()),
        Yaml::Integer(i) => Value::Number((*i).into()),
        Yaml::Boolean(b) => Value::Bool(*b),
        Yaml::Array(a) => Value::Array(a.iter().map(yaml_to_json).collect()),
        Yaml::Hash(h) => {
            let mut map = serde_json::Map::new();
            for (k, v) in h {
                if let Yaml::String(key) = k {
                    map.insert(key.clone(), yaml_to_json(v));
                }
            }
            Value::Object(map)
        }
        Yaml::Null => Value::Null,
        Yaml::BadValue => Value::Null,
        _ => Value::Null,
    }
}

#[pyclass(subclass)]
pub struct BaseSchemaGenerator {
    #[pyo3(get, set)]
    base_schema: Py<PyDict>,
}

#[pymethods]
impl BaseSchemaGenerator {
    #[new]
    fn new(base_schema: Py<PyDict>) -> Self {
        BaseSchemaGenerator { base_schema }
    }

    fn remove_converter(&self, path: String) -> String {
        let re = Regex::new(r":\w+}").unwrap();
        re.replace_all(&path, "}").into_owned()
    }

    fn parse_docstring(&self, docstring: Option<String>) -> String {
        match docstring {
            Some(doc) => {
                if doc.is_empty() {
                    return "".to_string();
                }   
                let part_of_docs: Vec<&str> = doc.split("---").collect();
                let part = part_of_docs.last().unwrap();

                match YamlLoader::load_from_str(&part) {
                    Ok(docs) => {
                        let doc = &docs[0];
                        let doc_json = yaml_to_json(doc);
                        return doc_json.to_string();
                    }
                    Err(_e) => {
                        return "".to_string();
                    }
                }
            }
            None => "".to_string(),
        }
    }
}
