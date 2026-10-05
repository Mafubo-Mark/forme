# Forme customer frontend

Deploy only `dist/` as the public static site. The current prototype keeps the operator panel, backend source, videos, database, and access keys on the owner's local computer.

The customer site has server-validated shared-key login, real video submission and status tracking, seven cover styles with rotatable 3D previews, preset and custom colors, and English / Traditional Chinese switching. Ordering and delivery are marked as upcoming; no fake payment or delivery state is created.

The site calls same-origin `/api/customer/*` and `/api/uploads/*`. The existing SSH reverse tunnel is for short-term integration testing only: the API stops when the owner's Mac is offline. The confirmed production goal is always-available login, upload, and status on a cloud API with durable storage; modeling may queue for a local worker. See the [production migration plan](deploy/ALWAYS_ON_ARCHITECTURE_ZH.md) and the [prototype handoff](deploy/CLAUDE_DEPLOY.md). Uploading static files alone will not enable login or video submission.

Template previews show style only. They are not personalized prosthetic cover geometry.
