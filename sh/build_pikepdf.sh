# Set environment variables
export CMAKE_ARGS="-DENABLE_QPDF=ON"
export QPDF_CFLAGS="-I$PREFIX/include"
export QPDF_LIBS="-L$PREFIX/lib -lqpdf"

# Install with build isolation disabled
pip install --no-build-isolation pikepdf