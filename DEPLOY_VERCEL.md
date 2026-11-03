# Deploying Willow Cross HMS to Vercel with Aiven MySQL

## 1. Aiven
1. Create a **MySQL** service (8.0 or newer). Wait until it shows *Running*.
2. On the service Overview page copy the **Service URI** and download the **CA certificate** (`ca.pem`).
   The URI looks like `mysql://avnadmin:PASSWORD@HOST:PORT/defaultdb?ssl-mode=REQUIRED`.
   `defaultdb` can be used as is, or create a database called `willow_cross_hms` and swap it into the URI.
3. Aiven's default allowed IPs is open to all, which Vercel needs (it has no fixed IP). Keep it that way.

## 2. Run migrations from your computer
Save the CA file as `certs/ca.pem`, then:
```bash
pip install -r requirements.txt
export SECRET_KEY=anything-long DEBUG=False
export DATABASE_URL="<your Service URI>"
python manage.py migrate
python manage.py createsuperuser
```
Do not run `seed_demo_data` on this database: it needs `DEBUG=True` and creates accounts with a known password.

## 3. Import to Vercel
Push the folder to GitHub, then Vercel > Add New > Project > import it. Framework preset: **Other**.

## 4. Environment variables
| Name | Value |
|---|---|
| `SECRET_KEY` | long random string (required) |
| `DEBUG` | `False` |
| `DATABASE_URL` | the Aiven Service URI |
| `DB_SSL_CA_PEM` | full contents of `ca.pem` (or commit `certs/ca.pem` instead) |
| `HOSPITAL_NAME`, `HOSPITAL_ADDRESS`, `HOSPITAL_PHONE` | optional |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | only for a custom domain |

Redeploy after setting them. Generate a key with
`python -c "import secrets;print(secrets.token_urlsafe(50))"`.

## Notes
- Each Vercel request opens its own database connection. Small Aiven plans have a connection limit, so
  watch it if traffic grows.
- Aiven keeps backups on paid plans; check the retention for patient data.
