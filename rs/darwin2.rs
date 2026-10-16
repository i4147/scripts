#!/data/data/com.termux/files/usr/bin/env rust-script
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use walkdir::WalkDir;

// Fixed patterns with proper glob support
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

// Improved pattern matching with proper glob support
fn matches_pattern(path: &Path, patterns: &[&str]) -> bool {
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let name_str = name.as_ref();

    for pattern in patterns {
        // Handle wildcard at end (e.g., "*.exe")
        if pattern.starts_with('*') && pattern.len() > 1 {
            let suffix = &pattern[1..];
            if name_str.ends_with(suffix) {
                return true;
            }
        }
        // Handle wildcard at beginning (e.g., "._*")
        else if pattern.ends_with('*') && pattern.len() > 1 {
            let prefix = &pattern[..pattern.len()-1];
            if name_str.starts_with(prefix) {
                return true;
            }
        }
        // Handle both ends (rare, but keep for completeness)
        else if pattern.contains('*') {
            let parts: Vec<&str> = pattern.split('*').collect();
            if parts.len() == 2 {
                if name_str.starts_with(parts[0]) && name_str.ends_with(parts[1]) {
                    return true;
                }
            }
        }
        // Exact match
        else if name_str == *pattern {
            return true;
        }
    }
    false
}

// More efficient directory size calculation using WalkDir
fn get_dir_size(path: &Path) -> u64 {
    WalkDir::new(path)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file())
        .filter_map(|e| e.metadata().ok())
        .map(|m| m.len())
        .sum()
}

// Fixed process_path to correctly calculate size before deletion
fn process_path(path: &Path, verbose: bool) -> (String, u64, bool) {
    let path_str = path.to_string_lossy().to_string();
    
    // Get size before deletion
    let size = if path.is_file() {
        fs::metadata(path).map(|m| m.len()).unwrap_or(0)
    } else if path.is_dir() {
        get_dir_size(path)
    } else {
        0
    };

    // Attempt deletion
    let result = if path.is_file() {
        fs::remove_file(path)
    } else if path.is_dir() {
        fs::remove_dir_all(path)
    } else {
        Ok(())
    };

    match result {
        Ok(_) => {
            if verbose && size > 0 {
                println!("Removed: {} ({} bytes)", path_str, size);
            }
            (path_str, size, true)
        }
        Err(e) => {
            eprintln!("Error deleting {}: {}", path_str, e);
            (path_str, 0, false)
        }
    }
}

// Optimized file collection using WalkDir
fn collect_matching_paths(root_dir: &Path) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    
    for entry in WalkDir::new(root_dir)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| {
            let path = e.path();
            matches_pattern(path, DARWIN_PATTERNS) || matches_pattern(path, WINDOWS_PATTERNS)
        }) {
        paths.push(entry.path().to_path_buf());
    }
    
    paths
}

fn find_and_remove_files(root_dir: &Path, num_workers: usize, verbose: bool) -> (usize, u64) {
    println!("Scanning {} for Darwin/Windows files...", root_dir.display());
    println!("Using {} worker threads\n", num_workers);

    // Collect all matching paths first
    let matching_paths = collect_matching_paths(root_dir);

    if matching_paths.is_empty() {
        println!("No matching files found.");
        return (0, 0);
    }

    println!("Found {} file(s) to remove\n", matching_paths.len());

    // Use atomic counter for better performance
    let total_freed = AtomicU64::new(0);
    let successful = AtomicU64::new(0);
    
    let (tx, rx) = mpsc::channel();
    let path_count = matching_paths.len();
    let paths_per_worker = (path_count + num_workers - 1) / num_workers;

    let mut handles = vec![];

    // Process chunks in parallel
    for chunk in matching_paths.chunks(paths_per_worker) {
        let tx = tx.clone();
        let chunk = chunk.to_vec();
        let verbose_clone = verbose;

        let handle = thread::spawn(move || {
            for path in chunk {
                let result = process_path(&path, verbose_clone);
                let _ = tx.send(result);
            }
        });

        handles.push(handle);
    }

    drop(tx);

    // Collect results
    while let Ok((_, size, success)) = rx.recv() {
        if success {
            successful.fetch_add(1, Ordering::Relaxed);
            total_freed.fetch_add(size, Ordering::Relaxed);
        }
    }

    // Wait for all threads
    for handle in handles {
        let _ = handle.join();
    }

    let successful_count = successful.load(Ordering::Relaxed) as usize;
    let total_freed_bytes = total_freed.load(Ordering::Relaxed);
    
    (successful_count, total_freed_bytes)
}

fn format_bytes(bytes: u64) -> String {
    const UNITS: [&str; 6] = ["B", "KB", "MB", "GB", "TB", "PB"];
    let mut size = bytes as f64;
    let mut unit_index = 0;

    while size >= 1024.0 && unit_index < UNITS.len() - 1 {
        size /= 1024.0;
        unit_index += 1;
    }

    format!("{:.2} {}", size, UNITS[unit_index])
}

fn print_report(files_removed: usize, total_freed_bytes: u64) {
    println!("{}", "=".repeat(60));
    println!("REMOVAL REPORT");
    println!("{}", "=".repeat(60));
    println!("Files removed: {}", files_removed);
    println!("Total disk space freed: {} ({} bytes)", 
             format_bytes(total_freed_bytes), total_freed_bytes);
    println!("{}\n", "=".repeat(60));
}

fn main() {
    let args: Vec<String> = std::env::args().collect();

    // Parse arguments more robustly
    let mut directory = ".".to_string();
    let mut num_workers = num_cpus();
    let mut verbose = false;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-w" | "--workers" => {
                if i + 1 < args.len() {
                    if let Ok(n) = args[i + 1].parse::<usize>() {
                        num_workers = n;
                        i += 1; // Skip the next argument
                    }
                }
            }
            "-v" | "--verbose" => verbose = true,
            arg if !arg.starts_with('-') => directory = arg.to_string(),
            _ => eprintln!("Unknown argument: {}", args[i]),
        }
        i += 1;
    }

    let root_dir = Path::new(&directory);

    if !root_dir.exists() {
        eprintln!("Error: {} does not exist", root_dir.display());
        return;
    }

    if !root_dir.is_dir() {
        eprintln!("Error: {} is not a directory", root_dir.display());
        return;
    }

    // Confirm before deletion for safety
    println!("WARNING: This will permanently delete files matching Darwin/Windows patterns.");
    println!("Directory: {}", root_dir.display());
    println!("Continue? [y/N]: ");
    
    let mut input = String::new();
    if let Err(e) = io::stdin().read_line(&mut input) {
        eprintln!("Error reading input: {}", e);
        return;
    }
    
    if !input.trim().eq_ignore_ascii_case("y") {
        println!("Operation cancelled.");
        return;
    }

    let (files_removed, total_freed_bytes) = find_and_remove_files(root_dir, num_workers, verbose);
    print_report(files_removed, total_freed_bytes);
}

fn num_cpus() -> usize {
    std::thread::available_parallelism()
        .map(|p| p.get())
        .unwrap_or(1)
}
