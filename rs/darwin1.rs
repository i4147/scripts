#!/data/data/com.termux/files/usr/bin/env rust-script
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

const DARWIN_PATTERNS: &[&str] = &[
    ".DS_Store",
    ".AppleDouble",
    ".LSOverride",
    ".TemporaryItems",
    ".Spotlight-V100",
    ".Trashes",
    "._*",
    ".com.apple.*",
];

const WINDOWS_PATTERNS: &[&str] = &[
    "*.exe",
    "*.dll",
    "*.sys",
    "*.bat",
    "*.cmd",
    "*.com",
    "*.msi",
    "*.scr",
    "*.lnk",
    "Thumbs.db",
    "desktop.ini",
    "$RECYCLE.BIN",
];

fn matches_pattern(path: &Path, patterns: &[&str]) -> bool {
    let name = path.file_name().unwrap_or_default().to_string_lossy();

    for pattern in patterns {
        if pattern.starts_with('*') {
            let suffix = &pattern[1..];
            if name.ends_with(suffix) {
                return true;
            }
        } else if pattern.starts_with("._") {
            if name.starts_with("._") {
                return true;
            }
        } else if pattern.starts_with('.') && *pattern != ".DS_Store" {
            if name.as_ref() == *pattern {
                return true;
            }
        } else if name.as_ref() == *pattern
            || name.starts_with(pattern.split('*').next().unwrap_or(""))
        {
            return true;
        }
    }
    false
}

fn get_dir_size(path: &Path) -> io::Result<u64> {
    let mut size = 0u64;
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            size += get_dir_size(&path)?;
        } else {
            size += fs::metadata(&path)?.len();
        }
    }
    Ok(size)
}

fn process_path(path: &Path) -> (String, u64) {
    let path_str = path.to_string_lossy().to_string();

    match fs::metadata(path) {
        Ok(metadata) => {
            let size = if metadata.is_file() {
                metadata.len()
            } else if metadata.is_dir() {
                get_dir_size(path).unwrap_or(0)
            } else {
                0
            };

            if let Err(e) = if metadata.is_file() {
                fs::remove_file(path)
            } else {
                fs::remove_dir_all(path)
            } {
                eprintln!("Error deleting {}: {}", path_str, e);
                (path_str, 0)
            } else {
                (path_str, size)
            }
        }
        Err(e) => {
            eprintln!("Error accessing {}: {}", path_str, e);
            (path_str, 0)
        }
    }
}

fn find_and_remove_files(root_dir: &Path, num_workers: usize) -> (usize, u64, Vec<(String, u64)>) {
    println!(
        "Scanning {} for Darwin/Windows files...",
        root_dir.display()
    );
    println!("Using {} worker threads\n", num_workers);

    let mut matching_paths = Vec::new();

    if let Ok(entries) = fs::read_dir(root_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if matches_pattern(&path, DARWIN_PATTERNS) || matches_pattern(&path, WINDOWS_PATTERNS) {
                matching_paths.push(path);
            }
            if path.is_dir() {
                collect_matching_paths(&path, &mut matching_paths);
            }
        }
    }

    if matching_paths.is_empty() {
        println!("No matching files found.");
        return (0, 0, vec![]);
    }

    println!("Found {} file(s) to remove\n", matching_paths.len());

    let (tx, rx) = mpsc::channel();
    let path_count = matching_paths.len();
    let paths_per_worker = (path_count + num_workers - 1) / num_workers;

    let mut handles = vec![];

    for chunk in matching_paths.chunks(paths_per_worker) {
        let tx = tx.clone();
        let chunk = chunk.to_vec();

        let handle = thread::spawn(move || {
            for path in chunk {
                let result = process_path(&path);
                let _ = tx.send(result);
            }
        });

        handles.push(handle);
    }

    drop(tx);

    let mut results = Vec::new();
    while let Ok(result) = rx.recv() {
        results.push(result);
    }

    for handle in handles {
        let _ = handle.join();
    }

    let total_freed: u64 = results.iter().map(|(_, size)| size).sum();
    let successful = results.iter().filter(|(_, size)| *size > 0).count();

    (successful, total_freed, results)
}

fn collect_matching_paths(dir: &Path, paths: &mut Vec<PathBuf>) {
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if matches_pattern(&path, DARWIN_PATTERNS) || matches_pattern(&path, WINDOWS_PATTERNS) {
                paths.push(path.clone());
            }
            if path.is_dir() {
                collect_matching_paths(&path, paths);
            }
        }
    }
}

fn format_bytes(mut bytes: u64) -> String {
    let units = ["B", "KB", "MB", "GB", "TB", "PB"];

    for unit in &units {
        if bytes < 1024 {
            return format!("{:.2} {}", bytes as f64, unit);
        }
        bytes /= 1024;
    }

    format!("{:.2} PB", bytes as f64)
}

fn print_report(files_removed: usize, total_freed_bytes: u64, total_freed_human: &str) {
    println!("{}", "=".repeat(60));
    println!("REMOVAL REPORT");
    println!("{}", "=".repeat(60));
    println!("Files removed: {}", files_removed);
    println!(
        "Total disk space freed: {} ({} bytes)",
        total_freed_human, total_freed_bytes
    );
    println!("{}\n", "=".repeat(60));
}

fn main() {
    let args: Vec<String> = std::env::args().collect();

    let directory = if args.len() > 1 {
        args[1].as_str()
    } else {
        "."
    };

    let num_workers = if let Some(pos) = args.iter().position(|a| a == "-w" || a == "--workers") {
        args.get(pos + 1)
            .and_then(|s| s.parse::<usize>().ok())
            .unwrap_or_else(|| num_cpus())
    } else {
        num_cpus()
    };

    let verbose = args.contains(&"-v".to_string()) || args.contains(&"--verbose".to_string());

    let root_dir = Path::new(directory);

    if !root_dir.exists() {
        eprintln!("Error: {} does not exist", root_dir.display());
        return;
    }

    let (files_removed, total_freed_bytes, results) = find_and_remove_files(root_dir, num_workers);

    let total_freed_human = format_bytes(total_freed_bytes);
    print_report(files_removed, total_freed_bytes, &total_freed_human);

    if verbose {
        println!("Removed files:");
        for (path, size) in results {
            if size > 0 {
                println!("  {} ({} bytes)", path, size);
            }
        }
    }
}

fn num_cpus() -> usize {
    std::thread::available_parallelism()
        .map(|p| p.get())
        .unwrap_or(1)
}
