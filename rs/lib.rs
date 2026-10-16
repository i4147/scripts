use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use std::path::PathBuf;

#[pyfunction]
fn walk(path: String, follow_links: Option<bool>) -> PyResult<Vec<String>> {
    let follow = follow_links.unwrap_or(false);

    let walker = jwalk::WalkDir::new(&path).follow_links(follow);

    let mut results = Vec::new();

    for entry in walker {
        match entry {
            Ok(e) => {
                results.push(e.path().to_string_lossy().to_string());
            }
            Err(e) => {
                return Err(PyOSError::new_err(format!(
                    "Error walking directory: {}",
                    e
                )));
            }
        }
    }

    Ok(results)
}

#[pyfunction]
fn walk_files(path: String, follow_links: Option<bool>) -> PyResult<Vec<String>> {
    let follow = follow_links.unwrap_or(false);

    let walker = jwalk::WalkDir::new(&path).follow_links(follow);

    let mut results = Vec::new();

    for entry in walker {
        match entry {
            Ok(e) => {
                if e.file_type().is_file() {
                    results.push(e.path().to_string_lossy().to_string());
                }
            }
            Err(e) => {
                return Err(PyOSError::new_err(format!(
                    "Error walking directory: {}",
                    e
                )));
            }
        }
    }

    Ok(results)
}

#[pyfunction]
fn walk_dirs(path: String, follow_links: Option<bool>) -> PyResult<Vec<String>> {
    let follow = follow_links.unwrap_or(false);

    let walker = jwalk::WalkDir::new(&path).follow_links(follow);

    let mut results = Vec::new();

    for entry in walker {
        match entry {
            Ok(e) => {
                if e.file_type().is_dir() {
                    results.push(e.path().to_string_lossy().to_string());
                }
            }
            Err(e) => {
                return Err(PyOSError::new_err(format!(
                    "Error walking directory: {}",
                    e
                )));
            }
        }
    }

    Ok(results)
}

/// Entry information with metadata
#[pyclass]
#[derive(Clone)]
struct Entry {
    #[pyo3(get)]
    path: String,
    #[pyo3(get)]
    is_file: bool,
    #[pyo3(get)]
    is_dir: bool,
    #[pyo3(get)]
    is_symlink: bool,
    #[pyo3(get)]
    depth: usize,
}

#[pyfunction]
fn walk_with_metadata(
    path: String,
    follow_links: Option<bool>,
    max_depth: Option<usize>,
    min_depth: Option<usize>,
) -> PyResult<Vec<Entry>> {
    let follow = follow_links.unwrap_or(false);

    let mut walker = jwalk::WalkDir::new(&path).follow_links(follow);

    if let Some(max) = max_depth {
        walker = walker.max_depth(max);
    }

    if let Some(min) = min_depth {
        walker = walker.min_depth(min);
    }

    let mut results = Vec::new();

    for entry in walker {
        match entry {
            Ok(e) => {
                let file_type = e.file_type();
                results.push(Entry {
                    path: e.path().to_string_lossy().to_string(),
                    is_file: file_type.is_file(),
                    is_dir: file_type.is_dir(),
                    is_symlink: file_type.is_symlink(),
                    depth: e.depth(),
                });
            }
            Err(e) => {
                return Err(PyOSError::new_err(format!(
                    "Error walking directory: {}",
                    e
                )));
            }
        }
    }

    Ok(results)
}

/// Parallel walk for better performance on large directories
#[pyfunction]
fn walk_parallel(
    path: String,
    follow_links: Option<bool>,
    num_threads: Option<usize>,
) -> PyResult<Vec<String>> {
    let follow = follow_links.unwrap_or(false);
    let threads = num_threads.unwrap_or(0); // 0 = auto

    let walker = jwalk::WalkDir::new(&path)
        .follow_links(follow)
        .parallelism(jwalk::Parallelism::RayonNewPool(threads));

    let mut results = Vec::new();

    for entry in walker {
        match entry {
            Ok(e) => {
                results.push(e.path().to_string_lossy().to_string());
            }
            Err(e) => {
                return Err(PyOSError::new_err(format!(
                    "Error walking directory: {}",
                    e
                )));
            }
        }
    }

    Ok(results)
}

/// A Python module implemented in Rust.
#[pymodule]
fn fastwalk(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk, m)?)?;
    m.add_function(wrap_pyfunction!(walk_files, m)?)?;
    m.add_function(wrap_pyfunction!(walk_dirs, m)?)?;
    m.add_function(wrap_pyfunction!(walk_with_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(walk_parallel, m)?)?;
    m.add_class::<Entry>()?;
    Ok(())
}


change the code so that in python side we can pass string or Path objects as arg to walk functions and get lust of Path object in return
