/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <stdbool.h>

char aera_rmtfs_uio_device[64];
int __real_storage_init(const char *root, bool read_only, bool partitions);
int __wrap_storage_init(const char *root, bool read_only, bool partitions)
{
    (void)read_only;
    return __real_storage_init(root, true, partitions);
}

int __real_open(const char *path, int flags, ...);
int __real_openat(int dirfd, const char *path, int flags, ...);

__attribute__((constructor)) static void init_logging(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}

// The only writable device is the explicitly checked volatile exchange RAM.
int __wrap_open(const char *path, int flags, ...)
{
    if ((flags & (O_CREAT | O_TRUNC | O_APPEND)) ||
        ((flags & O_ACCMODE) != O_RDONLY &&
         (!aera_rmtfs_uio_device[0] || strcmp(path, aera_rmtfs_uio_device)))) {
        fprintf(stderr, "WRITE GUARD rejected open: %s\n", path);
        errno = EROFS;
        return -1;
    }
    return __real_open(path, flags);
}

int __wrap_openat(int dirfd, const char *path, int flags, ...)
{
    if ((flags & (O_CREAT | O_TRUNC | O_APPEND)) || (flags & O_ACCMODE) != O_RDONLY) {
        errno = EROFS;
        return -1;
    }
    return __real_openat(dirfd, path, flags);
}

ssize_t __wrap_pwrite(int fd, const void *buf, size_t count, off_t offset)
{
    (void)fd; (void)buf; (void)count; (void)offset;
    errno = EROFS;
    return -1;
}

// Bionic FORTIFY redirects ordinary calls to these checked entry points.
// Route them through the same policy instead of leaving a second open path.
int __wrap___open_2(const char *path, int flags)
{
    return __wrap_open(path, flags);
}

int __wrap___openat_2(int dirfd, const char *path, int flags)
{
    return __wrap_openat(dirfd, path, flags);
}

ssize_t __wrap_pwrite64(int fd, const void *buf, size_t count, off64_t offset)
{
    (void)fd; (void)buf; (void)count; (void)offset;
    errno = EROFS;
    return -1;
}

ssize_t __wrap___pwrite_chk(int fd, const void *buf, size_t count, off_t offset,
                          size_t buffer_size)
{
    (void)buffer_size;
    return __wrap_pwrite(fd, buf, count, offset);
}

ssize_t __wrap___pwrite64_chk(int fd, const void *buf, size_t count, off64_t offset,
                            size_t buffer_size)
{
    (void)buffer_size;
    return __wrap_pwrite64(fd, buf, count, offset);
}
