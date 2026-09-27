# Forme — Custom Prosthetic Cover Platform

Forme is a responsive, framework-free demo for Hong Kong users to design a custom prosthetic cover. The flow includes video selection, an illustrative model preview, color and inspiration input, material selection, saved designs, demo checkout, orders, and delivery status.

## Run locally

Serve the `dist/` folder with any static web server. For example:

```bash
cd dist
python3 -m http.server 8000
```

Open `http://localhost:8000`. The demo account is `demo@forme.hk` with password `123456`.

## Demo behavior

- Video and image inputs validate locally, but files are **not uploaded**. Only their filenames are saved in the browser.
- The model preview is illustrative; no AI or Blender service is connected.
- Designs, orders, and the demo session are saved in browser local storage on the current device.
- Checkout does not charge money. A placed demo order is marked paid and delivered so the entire flow can be explored.
- Prices are intentionally "To be confirmed" until production pricing is available.
- Sign-in is a demo credential check, not production authentication.

## Pages

| Page | Purpose |
| --- | --- |
| `index.html` | Home and seven-step process |
| `login.html` | Demo account sign-in |
| `create.html` | Record, model, color, material design flow |
| `prosthetic.html` | Saved cover gallery with edit and order actions |
| `checkout.html` | Hong Kong address and demo order |
| `order.html` | Order history |
| `delivery.html` | Delivery status |
| `account.html` | Demo profile and activity |

## Backend integration

The frontend uses HTML, CSS, and vanilla JavaScript. API integration points are marked `API RESERVED` in `dist/js/main.js`:

| Method and path | Purpose |
| --- | --- |
| `POST /api/auth/login` | Authenticate a user |
| `POST /api/model/generate` | Upload a video and generate a model |
| `GET /api/colors/templates` | Load available finishes |
| `POST /api/prosthetic/save` | Save a design |
| `POST /api/order/create` | Create an order after payment |
| `POST /api/address/save` | Save a delivery address |
| `GET /api/order/list` | Load order history |
| `GET /api/delivery/status` | Load shipment updates |

`database/schema.sql` is a MySQL 8.0+ starter schema with `users`, `prosthetics`, `color_templates`, `orders`, and `deliveries`. Import it with `mysql -u root -p < database/schema.sql`. It does not seed a real login; the demo credential exists only in the frontend.

## Production work remaining

Connect a secure authentication service, file storage, 3D modeling service, live model viewer, pricing and Hong Kong payment provider, and carrier tracking. Validate cover fit and manufacturing details before accepting actual orders.
