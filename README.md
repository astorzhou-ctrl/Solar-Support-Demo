# Solar Support website: setup, owner guide and deployment

A Python (Flask) website for Solar Support with an owner admin panel. The owner can log in to update prices, upload photos and videos, edit text and pictures, and read customer quote requests.

## 1. What is in this folder

| Item | Purpose |
|---|---|
| `app.py` | The whole application: public site, admin panel, database. |
| `seed.py` | The starting content (text, products, prices, projects). Only used the first time the site starts. |
| `templates/` | Page layouts. `index.html` is the public site, `admin/` is the owner panel. |
| `static/` | Styles, scripts, photos, videos, brand logos and the `uploads/` folder for new files. |
| `instance/` | Created automatically. Holds the database (`solar.db`) and secret key. **Back this up.** |
| `manage.py` | Helper: run locally, reset the admin password. |
| `passenger_wsgi.py` | Start file for cPanel hosting. |
| `wsgi.py` | Start file for a VPS (gunicorn). |
| `requirements.txt` | Python packages: Flask and Pillow. |

## 2. Run it on your own computer

1. Install Python 3.10 or newer from <https://www.python.org/downloads/> (on Windows tick **Add python.exe to PATH**).
2. Open a terminal in this folder and run:

```
python -m venv venv
venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python manage.py run
```

3. Open <http://localhost:5000> for the website and <http://localhost:5000/admin> for the owner panel.
4. On first start the terminal prints a one-time admin password, and saves it in `instance/FIRST_LOGIN.txt`. Username is `admin`. You must choose your own password at first login (at least 10 characters), then delete `FIRST_LOGIN.txt`.
5. To choose the first password yourself, set it before the first start: `set ADMIN_PASSWORD=YourStrongPassword` (Windows) or `export ADMIN_PASSWORD=...` (Mac/Linux).
6. Forgotten password: `python manage.py set-password`.

## 3. Owner guide (for the Solar Support team)

Go to `www.your-domain/admin` (or the "Staff login" link in the website footer).

- **Update prices**: *Update prices* lists every product. Type the new US$ price, tick *Show price* to display it (untick to show "Request price"), untick *On website* to hide a product. Press **Save all prices**. The website changes immediately.
- **Products**: add, edit or delete products. Each has a picture, category, badge and a list of what is included. For complete systems, fill in inverter kVA, battery kWh and panel kW so the calculator can recommend them.
- **Projects**: add or edit project cards (title, client, kW, description, picture). Please do not put customer phone numbers in descriptions.
- **Photos and videos**: upload pictures (JPG, PNG, WebP) and short clips (MP4, WebM, up to 90 MB). They appear in the gallery. Keep videos short and compressed so they play quickly on mobile data.
- **Website text and pictures**: edit the banner, counters, About, Services, contact details, social links and the calculator appliance list. Replace any picture by uploading a new one.
- **Quote requests**: every enquiry from the form and calculator is stored here. Call or WhatsApp the customer, then mark it done.

Tips: use landscape photos of at least 1280 pixels wide for the banner pictures. After changing something, open the public site in a private window to see exactly what customers see.

## 4. Put it online

**Important:** this site is a Python application, so it needs hosting that can run Python. Ordinary "static" or WordPress-only plans cannot run it. Check before you buy:

- **WebZim** (<https://webzim.co.zw>) lists Python support on its cPanel hosting. Ask them to confirm "Setup Python App" is available on the plan, and which Python version.
- **GetHost** (<https://gethost.co.zw>) cPanel plans or its Cloud Server (VPS, from about US$14.95 a month at the time of writing). Ask support whether the cPanel plan includes "Setup Python App".
- Prices change, so confirm them at checkout.

### Option A: cPanel with "Setup Python App" (shared hosting)

1. Zip this whole folder (without any `venv` folder) and upload it in cPanel **File Manager** to a folder outside `public_html`, for example `/home/USER/solarsupport`. Extract it.
2. In cPanel open **Setup Python App** and click **Create Application**:
   - Python version: 3.10 or newer
   - Application root: `solarsupport`
   - Application URL: your domain
   - Application startup file: `passenger_wsgi.py`
   - Application Entry point: `application`
3. After it is created, use **Configuration files** / **Run Pip Install** with `requirements.txt` (or copy the command shown at the top of the page into the cPanel Terminal and run `pip install -r requirements.txt`).
4. Under **Environment variables** add: `SOLAR_HTTPS` = `1` and, if you want to choose the first password, `ADMIN_PASSWORD` = your password (remove this variable after first login).
5. Click **Restart**. Open your domain. Open `/admin` and log in. If you did not set `ADMIN_PASSWORD`, read the password in `instance/FIRST_LOGIN.txt` using File Manager.
6. Make sure the folders `instance` and `static/uploads` are writable by your account (permissions 755 normally work).

### Option B: a VPS (Ubuntu), for example GetHost Cloud Server

```
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /var/www/solarsupport && sudo chown $USER /var/www/solarsupport
# upload this folder's contents to /var/www/solarsupport, then:
cd /var/www/solarsupport && python3 -m venv venv && venv/bin/pip install -r requirements.txt gunicorn
```

Create `/etc/systemd/system/solarsupport.service`:

```
[Unit]
Description=Solar Support website
After=network.target
[Service]
User=www-data
WorkingDirectory=/var/www/solarsupport
Environment=SOLAR_HTTPS=1
ExecStart=/var/www/solarsupport/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
Restart=always
[Install]
WantedBy=multi-user.target
```

Then: `sudo chown -R www-data /var/www/solarsupport/instance /var/www/solarsupport/static/uploads`, `sudo systemctl enable --now solarsupport`.

Nginx site (`/etc/nginx/sites-available/solarsupport`, then link it into `sites-enabled`):

```
server {
  server_name yourdomain.co.zw www.yourdomain.co.zw;
  client_max_body_size 90m;
  location /static/ { alias /var/www/solarsupport/static/; expires 30d; }
  location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $remote_addr; }
}
```

Finish with `sudo nginx -t && sudo systemctl reload nginx` and `sudo certbot --nginx -d yourdomain.co.zw -d www.yourdomain.co.zw` for free HTTPS.

### Domain name

Register the domain (for example `.co.zw`, `.com`, `.org.zw`) in the client's own name with GetHost or WebZim, then point it at the hosting. On cPanel hosting, use the nameservers the host emails you. On a VPS, create an **A record** to the server's IP address.

## 5. Email alerts for new quote requests (optional)

Quote requests always appear in the admin panel. To also receive an email, set these environment variables (use an email account that allows SMTP over SSL, port 465):

```
SMTP_HOST=mail.yourdomain.co.zw
SMTP_PORT=465
SMTP_USER=info@yourdomain.co.zw
SMTP_PASSWORD=the-mailbox-password
NOTIFY_TO=info@eliumenergy.co.zw
```

## 6. Backups and updates

- **Back up regularly:** the `instance/` folder (database) and `static/uploads/` (photos and videos you added). Copy them to a safe place weekly.
- **Moving to a new host:** upload the folder, keep your `instance/` and `static/uploads/` folders, install requirements, restart.
- **Changing the starting text in `seed.py` does not change a live site.** Edit text in the admin panel instead.

## 7. Security notes

- Admin passwords are stored hashed; sessions are signed, HttpOnly and SameSite; every admin form has CSRF protection; login attempts are rate limited; uploads are checked and images are re-saved.
- Set `SOLAR_HTTPS=1` once the site runs on HTTPS so cookies are sent only over HTTPS.
- Never share the `instance/` folder or `secret.key`.
- The customer form has a hidden anti-spam field and an hourly limit per visitor.

## 8. Handover checklist

- [ ] Domain and hosting registered in the client's name, with login details given to the client
- [ ] Admin password changed by the client and `FIRST_LOGIN.txt` deleted
- [ ] Contact details, WhatsApp number and social links confirmed in *Website text and pictures*
- [ ] Prices confirmed in *Update prices*
- [ ] Project photos matched to the right projects (photos were matched by type, please confirm)
- [ ] Test the quote form and check the request appears in *Quote requests*
- [ ] Source code, this guide and a copy of `static/` handed over after full payment (see the signed terms)

## 9. Troubleshooting

| Problem | What to do |
|---|---|
| Page shows an error on cPanel | In Setup Python App, check the startup file is `passenger_wsgi.py` and the entry point is `application`, then Restart. |
| Uploads fail | Make `static/uploads` and `instance` writable, and keep files under 90 MB. |
| Cannot log in | Run `python manage.py set-password` (or set `ADMIN_PASSWORD` before first start on a fresh database). |
| Changes not showing | Hard refresh with Ctrl+Shift+R. |
| Fonts look different | Fonts load from Google Fonts. Without internet the site falls back to similar system fonts. |
