#!/bin/bash -eu
cd "$SRC/libzip/deps/zlib"
./configure --static --prefix="$WORK/zlib"
make -j"$(nproc)"
make install

cd "$SRC/libzip"
mkdir -p "$WORK/build"
cd "$WORK/build"
cmake "$SRC/libzip" \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_SHARED_LIBS=OFF \
    -DZLIB_INCLUDE_DIR="$WORK/zlib/include" \
    -DZLIB_LIBRARY="$WORK/zlib/lib/libz.a" \
    -DENABLE_BZIP2=OFF -DENABLE_LZMA=OFF -DENABLE_ZSTD=OFF \
    -DENABLE_OPENSSL=OFF -DENABLE_GNUTLS=OFF \
    -DENABLE_COMMONCRYPTO=OFF -DENABLE_WINDOWS_CRYPTO=OFF \
    -DBUILD_TOOLS=OFF -DBUILD_REGRESS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOC=OFF \
    -DBUILD_OSSFUZZ=OFF
make -j"$(nproc)" zip
$CXX $CXXFLAGS -I"$SRC/libzip/lib" -I"$WORK/build" \
    "$SRC/libzip/ossfuzz/zip_read_metadata_fuzzer.c" \
    -o "$OUT/zip_read_metadata_fuzzer" \
    $LIB_FUZZING_ENGINE "$WORK/build/lib/libzip.a" "$WORK/zlib/lib/libz.a"
