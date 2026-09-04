# AI-ShopKeepar — API Endpoint Reference

This document lists every HTTP endpoint exposed by the backend (FastAPI), grouped by router. It is meant for frontend developers integrating against this API.

## About This App

**AI-ShopKeepar** is an AI-powered business assistant for small shop owners (kirana stores, medical stores, etc.). A shop owner signs up, uploads their business documents (currently PDFs — invoices, bills, stock records, etc.), and the backend processes those documents into a searchable knowledge base (via embeddings + a FAISS vector store). The owner can then **ask plain-English questions about their own business data** (e.g. *"What were my total sales last month?"*, *"Which items are low in stock?"*) and get an AI-generated answer pulled from their uploaded documents — this is the core RAG (Retrieval-Augmented Generation) search feature.

Supporting features around that core flow:
- **Auth** — signup/signin with JWT, password reset via emailed OTP, and password change.
- **Document management** — upload, list, and replace business documents that feed the AI search.
- **Demo mode** — lets a user try the product instantly using pre-loaded sample data (e.g. a sample kirana/medical store dataset) instead of their own documents, useful for onboarding/trial before they upload real files.
- **Membership** — subscription plans (e.g. Free vs Premium) that gate limits like max documents or max queries/day; admins manage the plan catalog, users subscribe/cancel.

In short: **upload your shop's documents → ask questions in plain language → get instant AI-backed answers about your own business**, with account and subscription management wrapped around it.

- **Base URL (local dev):** `http://localhost:8000` (or whatever host/port the server is run on)
- **Content type:** All requests/responses are `application/json` unless noted otherwise (file upload endpoints use `multipart/form-data`).
- **Interactive docs:** FastAPI auto-generates Swagger UI at `/docs` and ReDoc at `/redoc` — useful for live testing alongside this doc.

---

## Authentication

Most endpoints require a JWT bearer token, obtained from `/auth/signin` (or `/auth/token`).

Send it on every protected request as:

```
Authorization: Bearer <access_token>
```

- Tokens are signed with `HS256` and expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default **60 minutes**, configurable via env var).
- If the token is missing, malformed, expired, or the user account is deactivated, the API responds `401 Unauthorized` (or `403 Forbidden` if the account is deactivated).
- Endpoints marked **Public** below need no token.
- Endpoints marked **Admin only** additionally require the authenticated user's `user_type` to be `admin`, otherwise `403 Forbidden` is returned.

---

## Table of Contents

1. [Root](#root)
2. [Auth (`/auth`)](#auth-auth)
3. [Document (`/document`)](#document-document)
4. [RAG Search (`/rag`)](#rag-search-rag)
5. [Demo Data (`/demo`)](#demo-data-demo)
6. [Membership (`/membership`)](#membership-membership)
7. [Common Error Format](#common-error-format)

---

## Root

### `GET /`
**Purpose:** Basic health check to confirm the API server is up.
**Auth:** Public

Health-check / sanity endpoint.

**Response `200 OK`**
```json
{ "Hello": "World" }
```

---

## Auth (`/auth`)

### `POST /auth/signup`
**Purpose:** First step of onboarding — creates the shop owner's account so they can log in and start using the app.
**Auth:** Public

Create a new shop-owner account.

**Request body**
```json
{
  "name": "Deepak Patel",
  "email": "owner@example.com",
  "username": "deepak_p",       // optional, 3+ chars, letters/numbers/underscore only, lowercased
  "password": "Passw0rd",        // 8+ chars, at least 1 uppercase + 1 number
  "phone": "9876543210",         // optional
  "shop_name": "My Kirana Store" // optional
}
```

**Response `201 Created`**
```json
{
  "id": 1,
  "name": "Deepak Patel",
  "email": "owner@example.com",
  "username": "deepak_p",
  "shop_name": "My Kirana Store",
  "plan": "free",
  "message": "Account created successfully"
}
```

**Errors**
| Status | Reason |
|---|---|
| `409 Conflict` | Email already registered |
| `409 Conflict` | Username already taken |
| `422 Unprocessable Entity` | Validation failure (weak password, short name/username, invalid email, etc.) |

---

### `POST /auth/signin`
**Purpose:** Log the user in and hand back the JWT the frontend must attach to every protected request afterward.
**Auth:** Public

Log in with email + password, receive a JWT.

**Request body**
```json
{
  "email": "owner@example.com",
  "password": "Passw0rd"
}
```

**Response `200 OK`**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "name": "Deepak Patel",
  "email": "owner@example.com",
  "shop_name": "My Kirana Store",
  "plan": "free"
}
```

**Errors**
| Status | Reason |
|---|---|
| `401 Unauthorized` | Incorrect email or password |
| `403 Forbidden` | Account deactivated |

---

### `POST /auth/me`
**Purpose:** Fetch the logged-in user's own profile — e.g. to populate an account/profile screen or restore session state on app load.
**Auth:** Required — but passed differently than usual (see note below)

Returns the profile of the user identified by the given token.

> ⚠️ **Note for frontend devs:** unlike other protected endpoints, this one does **not** read the standard `Authorization` header. It expects the token as a **query parameter** named `token`, whose value must literally include the `Bearer ` prefix, e.g.:
> `POST /auth/me?token=Bearer%20eyJhbGciOi...`
> There is no request body.

**Response `200 OK`** — the `ShopOwner` DB object (id, name, email, username, phone, shop_name, plan, is_active, user_type, created_at, last_login_at, etc.)

**Errors**
| Status | Reason |
|---|---|
| `401 Unauthorized` | Token format invalid, missing `Bearer ` prefix, invalid/expired token, or user not found |
| `403 Forbidden` | Account deactivated |

---

### `POST /auth/token`
**Purpose:** OAuth2-standard login used by Swagger's "Authorize" button and tools/clients expecting form-encoded OAuth2 password flow. Frontend apps should normally use `/auth/signin` instead.
**Auth:** Public

OAuth2-compatible token endpoint (mainly for Swagger UI's "Authorize" button). Functionally equivalent to `/auth/signin` but uses form-encoded credentials instead of JSON.

**Request body** — `application/x-www-form-urlencoded`
```
username=owner@example.com
password=Passw0rd
```
(`username` field carries the email)

**Response `200 OK`**
```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```

**Errors**
| Status | Reason |
|---|---|
| `401 Unauthorized` | Incorrect email or password |

---

### `POST /auth/forgot-password/send-code`
**Purpose:** "Forgot password" step 1 — user enters their email on the frontend, this triggers an emailed 6-digit OTP.
**Auth:** Public

Sends a 6-digit verification code to the user's email for password reset.

**Request body**
```json
{ "email": "owner@example.com" }
```

**Response `200 OK`** (always the same generic message, even if the email doesn't exist — prevents email enumeration)
```json
{ "message": "If an account with this email exists, a verification code has been sent." }
```

**Errors**
| Status | Reason |
|---|---|
| `429 Too Many Requests` | Resend requested within 60-second cooldown of the previous code |
| `500 Internal Server Error` | Email sending failed |

**Notes:** Code expires after `PASSWORD_RESET_CODE_EXPIRE_MINUTES` (default 10 min).

---

### `POST /auth/forgot-password/reset`
**Purpose:** "Forgot password" step 2 — user enters the OTP they received plus a new password to regain account access.
**Auth:** Public

Verifies the code sent above and sets a new password.

**Request body**
```json
{
  "email": "owner@example.com",
  "verification_code": "123456",   // exactly 6 digits
  "new_password": "NewPassw0rd",
  "confirm_password": "NewPassw0rd"
}
```

**Response `200 OK`**
```json
{ "message": "Password reset successfully. Please sign in with your new password." }
```

**Errors**
| Status | Reason |
|---|---|
| `400 Bad Request` | No pending reset code, code expired, or code incorrect |
| `429 Too Many Requests` | More than 5 failed verification attempts — must request a new code |
| `422 Unprocessable Entity` | `new_password` / `confirm_password` mismatch, or weak password |

---

### `POST /auth/change-password`
**Purpose:** Lets an already-logged-in user change their password from an account/settings screen (requires knowing the current password, unlike the forgot-password flow).
**Auth:** Required (Bearer token)

Lets a logged-in user change their own password.

**Request body**
```json
{
  "old_password": "Passw0rd",
  "new_password": "NewPassw0rd"
}
```

**Response `200 OK`**
```json
{ "message": "Password changed successfully" }
```

**Errors**
| Status | Reason |
|---|---|
| `401 Unauthorized` | Old password incorrect |
| `400 Bad Request` | New password same as old password |
| `422 Unprocessable Entity` | New password fails strength rules |

---

## Document (`/document`)

These endpoints manage the source documents that feed the AI search — this is where a shop owner's business data (invoices, bills, records) enters the system before it can be asked about via `/rag/search`. All endpoints require **Bearer token** auth. Only PDF files are currently accepted (`application/pdf`), max size **10 MB**. Documents are stored in a **private S3 bucket** — there is no public URL for a file; use `GET /document/{document_id}/download-url` to get a short-lived download link.

### `POST /document/upload-file`
**Purpose:** Upload a new business document so it can be processed and later queried through AI search.
**Auth:** Required

Uploads a document (PDF) for the current user. The file is uploaded to a private S3 bucket under a per-user/shop/date key prefix and a `Document` record is created for later RAG processing.

**Request** — `multipart/form-data`
| Field | Type | Description |
|---|---|---|
| `file` | file | The PDF file to upload |

**Response `201 Created`**
```json
{
  "id": 12,
  "original_name": "invoice.pdf",
  "file_type": "pdf",
  "file_size": 204800,
  "uploaded_at": "2026-08-31T10:15:00Z",
  "message": "File uploaded successfully"
}
```

**Errors**
| Status | Reason |
|---|---|
| `400 Bad Request` | Disallowed file type (only PDF supported) |
| `400 Bad Request` | File exceeds 10 MB |

---

### `GET /document/my-files`
**Purpose:** Power a "My Documents" screen showing everything the user has uploaded and whether each file has finished processing yet.
**Auth:** Required

Lists all documents uploaded by the current user, newest first.

**Response `200 OK`**
```json
{
  "total": 2,
  "files": [
    {
      "id": 12,
      "original_name": "invoice.pdf",
      "file_type": "pdf",
      "file_size_kb": 200.0,
      "uploaded_at": "2026-08-31T10:15:00Z",
      "process_status": "Pending",   // one of: Pending, Process, Rejected, Done, UPDATE
      "faiss_ids": null              // JSON string of vector-store chunk ids once processed
    }
  ]
}
```

Note: the bucket is private, so no file URL is included here. To view/download a specific file, call `GET /document/{document_id}/download-url` with its `id`.

---

### `GET /document/{document_id}/download-url`
**Purpose:** Get a short-lived, presigned S3 URL to actually download/view one document, since the bucket has no public access.
**Auth:** Required

Generates a fresh presigned URL each time it's called — deliberately not included in `GET /document/my-files`, since presigned URLs expire quickly and there's no point generating one for every file in a list the user hasn't opened yet. Call this endpoint on demand, right when the user wants to open a specific file.

**Path params**
| Param | Type | Description |
|---|---|---|
| `document_id` | int | ID of the document to get a download link for |

**Response `200 OK`**
```json
{
  "document_id": 12,
  "original_name": "invoice.pdf",
  "download_url": "https://<bucket>.s3.<region>.amazonaws.com/1/my_kirana_store/2026/08/31/abcd1234.pdf?X-Amz-Algorithm=...&X-Amz-Signature=...",
  "expires_in": 600
}
```

The `download_url` expires after `expires_in` seconds — request a new one if it's no longer needed by then.

**Errors**
| Status | Reason |
|---|---|
| `404 Not Found` | Document doesn't exist or isn't owned by the current user |
| `500 Internal Server Error` | Failed to generate the presigned URL |

---

### `PUT /document/edit/{document_id}`
**Purpose:** Let a user swap out an outdated/incorrect document (e.g. a corrected invoice) for a fresh version, which triggers re-processing into the AI search index.
**Auth:** Required

Replaces an existing document owned by the current user with a new file. The old file is deleted from S3 and re-processing is triggered (status set to `UPDATE`).

**Path params**
| Param | Type | Description |
|---|---|---|
| `document_id` | int | ID of the document to replace |

**Request** — `multipart/form-data`
| Field | Type | Description |
|---|---|---|
| `file` | file | The new PDF file |

**Response `200 OK`**
```json
{
  "message": "Document updated successfully. Processing will start shortly.",
  "document_id": 12,
  "original_name": "invoice_v2.pdf",
  "process_status": "UPDATE"
}
```

**Errors**
| Status | Reason |
|---|---|
| `404 Not Found` | Document doesn't exist or isn't owned by the current user |
| `400 Bad Request` | Disallowed file type or file exceeds 10 MB |

---

## RAG Search (`/rag`)

### `POST /rag/search`
**Purpose:** The core feature of the app — lets the user ask a plain-English question about their business and get an AI answer grounded in their own uploaded documents (or the demo dataset, if demo mode is on).
**Auth:** Required

Ask a natural-language question; the backend runs a RAG (Retrieval-Augmented Generation) search over the current user's processed documents (or demo dataset, if demo mode is enabled) and returns an AI-generated answer.

**Request body**
```json
{
  "query": "What was my total sales last month?",
  "top_k": 5   // optional, 1–20, default 5 — number of chunks retrieved for context
}
```

**Response `200 OK`**
```json
{
  "query": "What was my total sales last month?",
  "answer": "Based on your uploaded invoices, total sales last month were ₹45,000."
}
```

**Errors**
| Status | Reason |
|---|---|
| `400 Bad Request` | Query empty/whitespace only |
| `422 Unprocessable Entity` | Query shorter than 2 chars or longer than 500 chars |
| `500 Internal Server Error` | Search/RAG pipeline failed (`detail` includes the underlying error message) |

---

## Demo Data (`/demo`)

Lets a user try the product with pre-loaded sample data (e.g. a "kirana_store" or "medical_store" dataset) instead of uploading their own documents. All endpoints require **Bearer token** auth.

### `GET /demo/datasets`
**Purpose:** Populate a "try a sample dataset" picker (e.g. on an onboarding/empty-state screen) with the datasets the server actually has ready.
**Auth:** Required

Lists the demo datasets available on the server (i.e. those that have a pre-built FAISS index).

**Response `200 OK`**
```json
{ "datasets": ["kirana_store", "medical_store"] }
```

---

### `GET /demo/status`
**Purpose:** Check whether the current user is currently browsing demo data or their own, so the UI can show the right banner/toggle state.
**Auth:** Required

Returns the current user's demo-mode state.

**Response `200 OK`**
```json
{
  "demo_mode_enabled": true,
  "demo_dataset": "kirana_store"
}
```

---

### `POST /demo/enable`
**Purpose:** Switch the user into demo mode so they can explore `/rag/search` with realistic sample data before uploading their own documents.
**Auth:** Required

Turns on demo mode for the current user with the chosen dataset. While enabled, `/rag/search` answers from the demo dataset instead of the user's own documents.

**Request body**
```json
{ "dataset": "kirana_store" }
```

**Response `200 OK`**
```json
{
  "message": "Demo mode enabled",
  "demo_mode_enabled": true,
  "demo_dataset": "kirana_store"
}
```

**Errors**
| Status | Reason |
|---|---|
| `400 Bad Request` | `dataset` isn't one of the available datasets (response includes the valid list) |

---

### `POST /demo/disable`
**Purpose:** Switch the user back to their own real documents once they're done exploring the demo/sample data.
**Auth:** Required

Turns off demo mode for the current user, reverting `/rag/search` to the user's own documents.

**Response `200 OK`**
```json
{
  "message": "Demo mode disabled",
  "demo_mode_enabled": false,
  "demo_dataset": null
}
```

---

## Membership (`/membership`)

Membership plans (pricing tiers) and per-user subscriptions.

### `GET /membership/plans`
**Purpose:** Render a pricing/plans page (e.g. Free vs Premium) so users can compare and pick a plan to subscribe to.
**Auth:** Public

Lists all active plans, cheapest first — used for a pricing page.

**Response `200 OK`**
```json
[
  {
    "id": 1,
    "name": "free",
    "display_name": "Free Plan",
    "description": "Basic access",
    "price": 0.0,
    "duration_days": null,
    "max_documents": 5,
    "max_queries_per_day": 10,
    "is_active": true
  },
  {
    "id": 2,
    "name": "premium",
    "display_name": "Premium Plan",
    "description": "Unlimited access",
    "price": 499.0,
    "duration_days": 30,
    "max_documents": null,
    "max_queries_per_day": null,
    "is_active": true
  }
]
```

---

### `POST /membership/plans`
**Purpose:** Admin tool to add a new pricing tier to the catalog (not used by regular shop-owner users).
**Auth:** Required — **Admin only**

Creates a new membership plan.

**Request body**
```json
{
  "name": "premium",              // 2-50 chars, unique slug
  "display_name": "Premium Plan", // 2-100 chars
  "description": "Unlimited access",
  "price": 499.0,                 // >= 0
  "duration_days": 30,            // >= 1, omit/null = never expires
  "max_documents": null,          // >= 0, omit/null = unlimited
  "max_queries_per_day": null     // >= 0, omit/null = unlimited
}
```

**Response `201 Created`** — the created `PlanResponse` object (see shape above).

**Errors**
| Status | Reason |
|---|---|
| `403 Forbidden` | Current user is not an admin |
| `409 Conflict` | A plan with this `name` already exists |

---

### `PUT /membership/plans/{plan_id}`
**Purpose:** Admin tool to edit an existing plan's price, limits, or availability (e.g. adjust Premium pricing, or hide a plan by setting `is_active: false`).
**Auth:** Required — **Admin only**

Partially updates a plan. Only fields included in the body are changed.

**Path params:** `plan_id` (int)

**Request body** (all fields optional)
```json
{
  "display_name": "Premium Plan v2",
  "description": "Now with more features",
  "price": 599.0,
  "duration_days": 30,
  "max_documents": null,
  "max_queries_per_day": null,
  "is_active": true
}
```

**Response `200 OK`** — updated `PlanResponse`.

**Errors**
| Status | Reason |
|---|---|
| `403 Forbidden` | Not an admin |
| `404 Not Found` | Plan doesn't exist |

---

### `DELETE /membership/plans/{plan_id}`
**Purpose:** Admin tool to permanently remove a plan from the catalog that was never actually subscribed to (e.g. a mistakenly created plan).
**Auth:** Required — **Admin only**

Deletes a plan. Fails if any membership (past or present) references it — deactivate it instead (`is_active: false` via the update endpoint).

**Path params:** `plan_id` (int)

**Response `200 OK`**
```json
{ "message": "Plan deleted successfully" }
```

**Errors**
| Status | Reason |
|---|---|
| `403 Forbidden` | Not an admin |
| `404 Not Found` | Plan doesn't exist |
| `409 Conflict` | Plan has existing memberships tied to it |

---

### `GET /membership/my`
**Purpose:** Show the user's current subscription status on an account/billing screen (which plan they're on, when it expires).
**Auth:** Required

Returns the current user's active membership, or `null` if they have none.

**Response `200 OK`**
```json
{
  "id": 10,
  "status": "active",
  "started_at": "2026-08-01T00:00:00Z",
  "expires_at": "2026-08-31T00:00:00Z",
  "cancelled_at": null,
  "plan": { "id": 2, "name": "premium", "...": "..." }
}
```
or simply `null` if no active membership exists.

---

### `GET /membership/history`
**Purpose:** Show a full billing/subscription history list (e.g. "past plans") on an account screen.
**Auth:** Required

Returns all memberships (active, cancelled, expired) for the current user, newest first.

**Response `200 OK`** — array of `MembershipResponse` (same shape as `/membership/my`).

---

### `POST /membership/subscribe`
**Purpose:** Let a user actually purchase/activate a plan they picked on the pricing page (e.g. upgrade from Free to Premium).
**Auth:** Required

Subscribes the current user to a plan by name. Any existing active membership is automatically cancelled first (only one active membership per user at a time).

**Request body**
```json
{ "plan_name": "premium" }
```

**Response `201 Created`** — the new `MembershipResponse`.

**Errors**
| Status | Reason |
|---|---|
| `404 Not Found` | No active plan with that `plan_name` |

---

### `POST /membership/cancel`
**Purpose:** Let a user cancel their current paid plan from an account/billing screen.
**Auth:** Required

Cancels the current user's active membership.

**Response `200 OK`** — the now-cancelled `MembershipResponse`.

**Errors**
| Status | Reason |
|---|---|
| `404 Not Found` | User has no active membership to cancel |

---

## Common Error Format

Validation errors (`422`) follow FastAPI/Pydantic's default shape:
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "password"],
      "msg": "Value error, Password must be at least 8 characters",
      "input": "abc"
    }
  ]
}
```

All other handled errors (`400`, `401`, `403`, `404`, `409`, `429`) return:
```json
{ "detail": "Human-readable error message" }
```

Any unhandled server exception returns a generic `500`:
```json
{ "detail": "Internal server error" }
```

---

## Enum Reference

**`process_status`** (Document):
`Pending` → not yet embedded into the vector store · `Process` → currently being processed · `Done` → ready for RAG search · `Rejected` → processing failed · `UPDATE` → re-uploaded, awaiting re-processing.

**`status`** (Membership): `active` · `expired` · `cancelled`

**`user_type`** (ShopOwner): `admin` · `member`

**`plan`** (ShopOwner, legacy top-level field also returned on signin/signup): `free` · `premium`
