#!/bin/bash -eu
cd "$SRC/zxc"
LIB_SOURCES="src/lib/zxc_common.c src/lib/zxc_compress.c src/lib/zxc_decompress.c src/lib/zxc_dict.c src/lib/zxc_driver.c src/lib/zxc_dispatch.c src/lib/zxc_huffman.c src/lib/zxc_pivco_tables.c src/lib/zxc_pstream.c src/lib/zxc_seekable.c"
$CC $CFLAGS -I include -I src/lib/vendors \
    -DZXC_FUNCTION_SUFFIX=_default -DZXC_ONLY_DEFAULT \
    $LIB_SOURCES tests/fuzz_decompress.c \
    -o "$OUT/zxc_fuzzer_decompress" $LIB_FUZZING_ENGINE -lm -pthread
