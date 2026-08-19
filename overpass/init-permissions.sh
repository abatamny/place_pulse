#!/bin/sh

# The named-volume root is created with owner-only traversal on Docker Desktop.
# The internal FastCGI worker needs to reach the dispatcher sockets in /db/db.
chmod 0755 /db
