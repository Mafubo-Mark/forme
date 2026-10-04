# Forme customer frontend

Deploy only `dist/` as the public static site. The operator panel, backend source, videos, database, and access keys stay on the owner's local computer.

The customer site has server-validated shared-key login, real video submission and status tracking, seven cover styles with rotatable 3D previews, preset and custom colors, and English / Traditional Chinese switching. Ordering and delivery are marked as upcoming; no fake payment or delivery state is created.

The site calls same-origin `/api/customer/*` and `/api/uploads/*`. The cloud server must proxy those paths through a private SSH reverse tunnel to the local backend. See [deployment handoff](deploy/CLAUDE_DEPLOY.md). Uploading static files alone will not enable login or video submission.

Template previews show style only. They are not personalized prosthetic cover geometry.
