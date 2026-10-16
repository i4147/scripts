# Install pure Python implementation (slower but works)
#pip install grpcio # or
# Set GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
export GRPC_PYTHON_BUILD_SYSTEM_CARES=1
export GRPC_PYTHON_BUILD_SYSTEM_ABSL=1
export BUILD_WITH_SYSTEM_ABSL=1
export BUILD_WITH_SYSTEM_OPENSSL=1
export BUILD_WITH_SYSTEM_ZLIB=1
export BUILD_WITH_SYSTEM_CARES=1

# export GRPC_BUILD_WITH_BORING_SSL_ASM=0
# Disable parallel compilation (often fixes issues)
export GRPC_PYTHON_BUILD_EXT_COMPILER_JOBS=1

GRPC_PYTHON_DISABLE_LIBC_COMPILATION=1 python setup.py bdist_wheel --verbose
