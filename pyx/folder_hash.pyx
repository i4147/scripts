import os
import hashlib
from libc.stdio cimport FILE, fopen, fread, fclose
from libc.stdlib cimport malloc, free

cdef size_t BUFFER_SIZE = 65536

cdef class FolderHasher:
    cdef object _hash_func
    cdef bint _follow_links
    cdef bytes _root_path
    
    def __cinit__(self, str root_path, bint follow_links = False, str hash_algorithm = "sha256"):
        self._root_path = root_path.encode('utf-8')
        self._follow_links = follow_links
        
        if hash_algorithm == "sha256":
            self._hash_func = hashlib.sha256
        elif hash_algorithm == "md5":
            self._hash_func = hashlib.md5
        elif hash_algorithm == "sha1":
            self._hash_func = hashlib.sha1
        elif hash_algorithm == "blake2b":
            self._hash_func = hashlib.blake2b
        else:
            raise ValueError(f"Unsupported hash algorithm: {hash_algorithm}")
    
    def compute_hash(self) -> str:
        """Compute hash of the entire folder."""
        cdef object hash_obj = self._hash_func()
        self._process_directory(self._root_path, hash_obj, b"")
        return hash_obj.hexdigest()
    
    cdef void _process_directory(self, bytes path, object hash_obj, bytes rel_path) except *:
        """Process directory recursively."""
        cdef bytes full_path
        cdef bytes entry_name
        cdef bytes new_rel_path
        
        try:
            entries = os.listdir(path)
            # Sort for consistent hashing
            entries.sort()
            
            for entry in entries:
                if isinstance(entry, str):
                    entry_name = entry.encode('utf-8')
                else:
                    entry_name = entry
                
                full_path = os.path.join(path, entry_name)
                
                # Build relative path
                if rel_path == b"":
                    new_rel_path = entry_name
                else:
                    new_rel_path = rel_path + b"/" + entry_name
                
                # Add path to hash
                hash_obj.update(new_rel_path)
                
                if os.path.isdir(full_path):
                    if not self._follow_links and os.path.islink(full_path):
                        continue
                    self._process_directory(full_path, hash_obj, new_rel_path)
                else:
                    if not self._follow_links and os.path.islink(full_path):
                        continue
                    self._hash_file_fast(full_path, hash_obj)
                    
        except (OSError, PermissionError) as e:
            print(f"Warning: Cannot access {path}: {e}")
    
    cdef void _hash_file_fast(self, bytes file_path, object hash_obj) except *:
        """Fast file hashing using C file operations."""
        cdef FILE* file_ptr
        cdef unsigned char* buffer
        cdef size_t bytes_read
        
        # Convert Python bytes to C string
        cdef char* c_file_path = file_path
        
        file_ptr = fopen(c_file_path, "rb")
        if file_ptr == NULL:
            # If we can't open with C, fall back to Python
            self._hash_file_python(file_path, hash_obj)
            return
        
        buffer = <unsigned char*>malloc(BUFFER_SIZE * sizeof(unsigned char))
        if buffer == NULL:
            fclose(file_ptr)
            self._hash_file_python(file_path, hash_obj)
            return
        
        try:
            while True:
                bytes_read = fread(buffer, 1, BUFFER_SIZE, file_ptr)
                if bytes_read == 0:
                    break
                # Convert buffer slice to Python bytes for hashing
                hash_obj.update(<char*>buffer[:bytes_read])
        except:
            fclose(file_ptr)
            free(buffer)
            raise
        
        fclose(file_ptr)
        free(buffer)
    
    cdef void _hash_file_python(self, bytes file_path, object hash_obj) except *:
        """Fallback to Python file reading."""
        cdef str file_path_str = file_path.decode('utf-8')
        
        try:
            with open(file_path_str, 'rb') as f:
                while True:
                    chunk = f.read(BUFFER_SIZE)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
        except (OSError, IOError) as e:
            print(f"Warning: Cannot read file {file_path}: {e}")

# Content-only hasher (ignores file paths)
cdef class ContentOnlyHasher(FolderHasher):
    cdef void _process_directory(self, bytes path, object hash_obj, bytes rel_path) except *:
        """Process directory but only hash file contents."""
        cdef bytes full_path
        
        try:
            entries = os.listdir(path)
            entries.sort()  # Sort for consistent ordering
            
            for entry in entries:
                if isinstance(entry, str):
                    entry_name = entry.encode('utf-8')
                else:
                    entry_name = entry
                
                full_path = os.path.join(path, entry_name)
                
                if os.path.isdir(full_path):
                    if not self._follow_links and os.path.islink(full_path):
                        continue
                    self._process_directory(full_path, hash_obj, b"")
                else:
                    if not self._follow_links and os.path.islink(full_path):
                        continue
                    self._hash_file_fast(full_path, hash_obj)
                    
        except (OSError, PermissionError) as e:
            print(f"Warning: Cannot access {path}: {e}")

# Public API functions
def hash_folder(str folder_path, bint follow_links = False, str hash_algorithm = "sha256") -> str:
    """
    Compute hash of a folder including structure and contents.
    
    Args:
        folder_path: Path to folder
        follow_links: Follow symbolic links
        hash_algorithm: Hash algorithm to use
    
    Returns:
        Hexadecimal hash string
    """
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    
    if not os.path.isdir(folder_path):
        raise ValueError(f"Path is not a directory: {folder_path}")
    
    hasher = FolderHasher(folder_path, follow_links, hash_algorithm)
    return hasher.compute_hash()

def hash_folder_contents(str folder_path, bint follow_links = False, str hash_algorithm = "sha256") -> str:
    """
    Compute hash of folder contents only (ignores file paths).
    
    Args:
        folder_path: Path to folder
        follow_links: Follow symbolic links
        hash_algorithm: Hash algorithm to use
    
    Returns:
        Hexadecimal hash string
    """
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    
    if not os.path.isdir(folder_path):
        raise ValueError(f"Path is not a directory: {folder_path}")
    
    hasher = ContentOnlyHasher(folder_path, follow_links, hash_algorithm)
    return hasher.compute_hash()

def get_folder_stats(str folder_path) -> dict:
    """
    Get statistics about folder for debugging.
    
    Returns:
        Dictionary with file_count, total_size, etc.
    """
    cdef int file_count = 0
    cdef long total_size = 0
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                total_size += os.path.getsize(file_path)
                file_count += 1
            except OSError:
                continue
    
    return {
        'file_count': file_count,
        'total_size': total_size,
        'total_size_mb': total_size / (1024 * 1024)
    }
