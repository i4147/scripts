#!/data/data/com.termux/files/usr/bin/env rust-script

use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::thread;
use std::time::Instant;

const CHUNK_SIZE: usize = 32768;

fn should_skip(path: &Path) -> bool {
    if path.is_symlink() {
        return true;
    }

    if let Ok(metadata) = path.metadata() {
        if metadata.len() == 0 {
            return true;
        }
    } else {
        return true;
    }

    let skip_patterns = [".git", "__pycache__", ".mypy_cache", ".ruff_cache"];
    for component in path.components() {
        if let Some(name) = component.as_os_str().to_str() {
            if skip_patterns.contains(&name) {
                return true;
            }
        }
    }

    false
}

fn compute_xxh64(path: &Path) -> io::Result<(String, PathBuf)> {
    let mut file = File::open(path)?;
    let mut hasher = xxh64::Hasher::new();
    let mut buffer = vec![0; CHUNK_SIZE];

    loop {
        let bytes_read = file.read(&mut buffer)?;
        if bytes_read == 0 {
            break;
        }
        hasher.update(&buffer[..bytes_read]);
    }

    Ok((hasher.finalize().to_hex_string(), path.to_path_buf()))
}

fn format_size(size: u64) -> String {
    const UNITS: [&str; 6] = ["B", "KB", "MB", "GB", "TB", "PB"];
    let mut size = size as f64;
    let mut unit_idx = 0;

    while size >= 1024.0 && unit_idx < UNITS.len() - 1 {
        size /= 1024.0;
        unit_idx += 1;
    }

    format!("{:.2} {}", size, UNITS[unit_idx])
}

fn print_colored(text: &str, color: &str) {
    // Simple colored output using ANSI codes
    let color_code = match color {
        "cyan" => "\x1b[36m",
        "yellow" => "\x1b[33m",
        "green" => "\x1b[32m",
        "red" => "\x1b[31m",
        _ => "",
    };
    let reset = "\x1b[0m";
    println!("{}{}{}", color_code, text, reset);
}

fn find_duplicates() -> io::Result<()> {
    let cwd = std::env::current_dir()?;
    let start_time = Instant::now();

    // First pass: collect all files with their sizes
    let mut files_with_sizes = Vec::new();
    let mut total_files = 0;
    let mut skipped_files = 0;

    for entry in walkdir::WalkDir::new(&cwd)
        .into_iter()
        .filter_entry(|e| !should_skip(e.path()))
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if entry.file_type().is_file() {
            if let Ok(metadata) = entry.metadata() {
                let size = metadata.len();
                if size > 0 {
                    files_with_sizes.push((entry.path().to_path_buf(), size));
                    total_files += 1;
                } else {
                    skipped_files += 1;
                }
            }
        }
    }

    println!("Found {} files to process (skipped {})", total_files, skipped_files);

    // Group by size
    let mut files_by_size: HashMap<u64, Vec<PathBuf>> = HashMap::new();
    for (path, size) in files_with_sizes {
        files_by_size.entry(size).or_insert_with(Vec::new).push(path);
    }

    // Collect files that have potential duplicates (same size)
    let mut paths_to_hash = Vec::new();
    for paths in files_by_size.values() {
        if paths.len() > 1 {
            paths_to_hash.extend(paths.iter().cloned());
        }
    }

    println!("Scanning {} files for duplicates...", paths_to_hash.len());

    // Compute hashes in parallel using threads
    let (tx, rx) = mpsc::channel();
    let mut handles = Vec::new();

    // Split work among threads
    let chunk_size = (paths_to_hash.len() + 7) / 8; // 8 threads
    for chunk in paths_to_hash.chunks(chunk_size) {
        let tx = tx.clone();
        let chunk = chunk.to_vec();
        let handle = thread::spawn(move || {
            let mut results = Vec::new();
            for path in chunk {
                if let Ok((hash, path)) = compute_xxh64(&path) {
                    results.push((hash, path));
                }
            }
            tx.send(results).unwrap();
        });
        handles.push(handle);
    }

    // Collect results
    let mut files_by_hash: HashMap<String, Vec<PathBuf>> = HashMap::new();
    for handle in handles {
        handle.join().unwrap();
    }

    // Receive all results
    while let Ok(results) = rx.try_recv() {
        for (hash, path) in results {
            files_by_hash.entry(hash).or_insert_with(Vec::new).push(path);
        }
    }

    // Process duplicates
    let mut duplicate_count = 0;
    let mut total_size = 0;
    let mut duplicates_found = Vec::new();

    for (hash, paths) in &files_by_hash {
        if paths.len() > 1 {
            duplicate_count += paths.len() - 1;
            println!("\nHash {}:", hash);
            for path in paths {
                if let Ok(relative) = path.strip_prefix(&cwd) {
                    print_colored(&format!("  - {}", relative.display()), "cyan");
                    if let Ok(metadata) = path.metadata() {
                        total_size += metadata.len();
                    }
                }
            }
        }
    }

    if duplicate_count > 0 {
        println!("\n{}", "=".repeat(50));
        print_colored(&format!("Removing {} duplicate files...", duplicate_count), "yellow");

        for (hash, paths) in &files_by_hash {
            if paths.len() > 1 {
                // Keep the first file, remove the rest
                for path in &paths[1..] {
                    if let Ok(relative) = path.strip_prefix(&cwd) {
                        print_colored(&format!("  - {} removed", relative.display()), "yellow");
                        if let Err(e) = fs::remove_file(path) {
                            println!("  Error removing {}: {}", relative.display(), e);
                        }
                    }
                }
            }
        }
    }

    let elapsed = start_time.elapsed();
    println!("\n{}", "=".repeat(50));
    print_colored(&format!("Total duplicates found: {}", duplicate_count), "cyan");
    print_colored(&format!("Total size of duplicates: {}", format_size(total_size)), "cyan");
    print_colored(&format!("Space saved: {}", format_size(total_size)), "green");
    println!("Time taken: {:.2?}", elapsed);

    Ok(())
}

// Simple XXH64 implementation
mod xxh64 {
    const PRIME1: u64 = 11400714785074694791;
    const PRIME2: u64 = 14029467366897019727;
    const PRIME3: u64 = 1609587929392839161;
    const PRIME4: u64 = 9650029242287828579;
    const PRIME5: u64 = 2870177450012600261;

    pub struct Hasher {
        state: [u64; 4],
        buffer: Vec<u8>,
        total_len: u64,
    }

    impl Hasher {
        pub fn new() -> Self {
            Hasher {
                state: [
                    PRIME1 + PRIME2,
                    PRIME2,
                    PRIME3,
                    PRIME4 - PRIME1,
                ],
                buffer: Vec::with_capacity(32),
                total_len: 0,
            }
        }

        pub fn update(&mut self, data: &[u8]) {
            self.total_len += data.len() as u64;
            self.buffer.extend_from_slice(data);

            while self.buffer.len() >= 32 {
                let chunk = self.buffer.drain(..32).collect::<Vec<_>>();
                self.process_chunk(&chunk);
            }
        }

        fn process_chunk(&mut self, chunk: &[u8]) {
            let mut lanes: [u64; 4] = [
                self.state[0],
                self.state[1],
                self.state[2],
                self.state[3],
            ];

            for (i, lane) in lanes.iter_mut().enumerate() {
                let offset = i * 8;
                let val = u64::from_le_bytes([
                    chunk[offset],
                    chunk[offset + 1],
                    chunk[offset + 2],
                    chunk[offset + 3],
                    chunk[offset + 4],
                    chunk[offset + 5],
                    chunk[offset + 6],
                    chunk[offset + 7],
                ]);
                *lane = lane.wrapping_add(val);
                *lane = lane.wrapping_mul(PRIME2);
                *lane = rotate_left(*lane, 31);
                *lane = lane.wrapping_mul(PRIME1);
            }

            self.state[0] = self.state[0].wrapping_add(lanes[0]);
            self.state[1] = self.state[1].wrapping_add(lanes[1]);
            self.state[2] = self.state[2].wrapping_add(lanes[2]);
            self.state[3] = self.state[3].wrapping_add(lanes[3]);
        }

        pub fn finalize(&self) -> u64 {
            let mut h64 = self.state[0].wrapping_add(self.state[1])
                .wrapping_add(self.state[2])
                .wrapping_add(self.state[3])
                .wrapping_add(self.total_len);

            // Process remaining bytes
            let mut buffer = self.buffer.clone();
            let mut i = 0;
            let len = buffer.len();

            while i + 8 <= len {
                let val = u64::from_le_bytes([
                    buffer[i],
                    buffer[i + 1],
                    buffer[i + 2],
                    buffer[i + 3],
                    buffer[i + 4],
                    buffer[i + 5],
                    buffer[i + 6],
                    buffer[i + 7],
                ]);
                h64 = h64.wrapping_add(val);
                h64 = h64.wrapping_mul(PRIME2);
                h64 = rotate_left(h64, 33);
                h64 = h64.wrapping_mul(PRIME3);
                i += 8;
            }

            while i < len {
                h64 = h64.wrapping_add((buffer[i] as u64) << (8 * (i & 7)));
                i += 1;
            }

            // Final mixing
            h64 ^= h64 >> 33;
            h64 = h64.wrapping_mul(PRIME2);
            h64 ^= h64 >> 29;
            h64 = h64.wrapping_mul(PRIME3);
            h64 ^= h64 >> 32;

            h64
        }

        pub fn to_hex_string(&self) -> String {
            format!("{:016x}", self.finalize())
        }
    }

    fn rotate_left(x: u64, r: u32) -> u64 {
        (x << r) | (x >> (64 - r))
    }
}

// Simple walkdir implementation to avoid dependency
mod walkdir {
    use std::fs;
    use std::io;
    use std::path::{Path, PathBuf};

    pub struct WalkDir {
        stack: Vec<PathBuf>,
    }

    impl WalkDir {
        pub fn new<P: AsRef<Path>>(path: P) -> Self {
            WalkDir {
                stack: vec![path.as_ref().to_path_buf()],
            }
        }

        pub fn into_iter(self) -> WalkDirIter {
            WalkDirIter {
                stack: self.stack,
                filter_entry: None,
            }
        }

        pub fn filter_entry<F>(self, filter: F) -> WalkDirIter
        where
            F: Fn(&DirEntry) -> bool + 'static,
        {
            WalkDirIter {
                stack: self.stack,
                filter_entry: Some(Box::new(filter)),
            }
        }
    }

    pub struct DirEntry {
        path: PathBuf,
        file_type: fs::FileType,
        metadata: fs::Metadata,
    }

    impl DirEntry {
        pub fn path(&self) -> &Path {
            &self.path
        }

        pub fn file_type(&self) -> fs::FileType {
            self.file_type
        }

        pub fn metadata(&self) -> io::Result<fs::Metadata> {
            Ok(self.metadata.clone())
        }
    }

    pub struct WalkDirIter {
        stack: Vec<PathBuf>,
        filter_entry: Option<Box<dyn Fn(&DirEntry) -> bool>>,
    }

    impl Iterator for WalkDirIter {
        type Item = io::Result<DirEntry>;

        fn next(&mut self) -> Option<Self::Item> {
            while let Some(path) = self.stack.pop() {
                match fs::symlink_metadata(&path) {
                    Ok(metadata) => {
                        let file_type = metadata.file_type();
                        let entry = DirEntry {
                            path: path.clone(),
                            file_type,
                            metadata: metadata.clone(),
                        };

                        // Check if we should skip this entry
                        if let Some(ref filter) = self.filter_entry {
                            if !filter(&entry) {
                                continue;
                            }
                        }

                        if file_type.is_dir() {
                            if let Ok(read_dir) = fs::read_dir(&path) {
                                for entry in read_dir.flatten() {
                                    self.stack.push(entry.path());
                                }
                            }
                        }

                        return Some(Ok(entry));
                    }
                    Err(e) => return Some(Err(e)),
                }
            }
            None
        }
    }
}

fn main() {
    if let Err(e) = find_duplicates() {
        eprintln!("Error: {}", e);
        std::process::exit(1);
    }
}
