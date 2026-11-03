Optional: save Aiven's CA certificate here as `ca.pem` (Aiven console > your MySQL service > Overview > "CA certificate" > Download).
It is a public certificate, so it is safe to commit. On Vercel you can instead set the DB_SSL_CA_PEM environment variable.
