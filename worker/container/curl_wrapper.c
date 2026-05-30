#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <sys/wait.h>
#include <pwd.h>
#include <sys/stat.h>
#include <openssl/sha.h>
#include <limits.h>

#define LOG_FILE "/home/net_user/external_deps.log"

void calc_sha256_file(const char *filename, char *output_hex) {
    unsigned char hash[SHA256_DIGEST_LENGTH];
    unsigned char buf[4096];
    size_t n;

    FILE *f = fopen(filename, "rb");
    if (!f) {
        strcpy(output_hex, "no-output-file");
        return;
    }

    SHA256_CTX sha256;
    SHA256_Init(&sha256);
    while ((n = fread(buf, 1, sizeof(buf), f)) > 0) {
        SHA256_Update(&sha256, buf, n);
    }
    SHA256_Final(hash, &sha256);
    fclose(f);

    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        sprintf(output_hex + (i * 2), "%02x", hash[i]);
    }
    output_hex[64] = '\0';
}

int main(int argc, char *argv[]) {

    // Si lo ejecuta root, bajar a net_user para loguear igual
    if (getuid() == 0) {
        struct passwd *pw = getpwnam("net_user");
        if (pw) {
            setgid(pw->pw_gid);
            setuid(pw->pw_uid);
        }
    }

    char *output_file = NULL;
    for (int i = 1; i < argc - 1; i++) {
        if (strcmp(argv[i], "-o") == 0 || strcmp(argv[i], "--output") == 0) {
            output_file = argv[i + 1];
            break;
        }
    }


    int capital_O = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-O") == 0) {
            capital_O = 1;
            break;
        }
    }

    // Buscar URL antes del fork
    char *url = NULL;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "http://", 7) == 0 || strncmp(argv[i], "https://", 8) == 0) {
            url = argv[i];
            break;
        }
    }

    static char inferred_path[PATH_MAX];
    if (!output_file && capital_O && url) {
        char *last_slash = strrchr(url, '/');
        if (last_slash && *(last_slash + 1) != '\0') {
            char filename[PATH_MAX];
            strncpy(filename, last_slash + 1, sizeof(filename) - 1);
            filename[sizeof(filename) - 1] = '\0';
            char *q = strchr(filename, '?');
            if (q) *q = '\0';
            char cwd[PATH_MAX];
            if (getcwd(cwd, sizeof(cwd))) {
                snprintf(inferred_path, sizeof(inferred_path),
                         "%s/%s", cwd, filename);
                output_file = inferred_path;
            }
        }
    }



    pid_t pid = fork();
    if (pid == 0) {
        // HIJO: ejecutar curl.real como net_user (tiene red por iptables)
        // ya somos net_user por setuid, ejecutamos directamente
        execv("/usr/bin/curl.real", argv);
        perror("execv curl.real failed");
        exit(1);
    }

    int status;
    waitpid(pid, &status, 0);

    int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 1;

    if (exit_code == 0) {
        char hash[65];

        if (output_file && access(output_file, F_OK) == 0) {
            calc_sha256_file(output_file, hash);
        } else {
            strcpy(hash, "no-output-file");
        }

        // Escribir log como net_user (ya somos net_user)
        FILE *log = fopen(LOG_FILE, "a");
        if (log) {
            fprintf(log, "%s %s\n", hash, url ? url : "no-url");
            fclose(log);
        }
    }

    return exit_code;
}