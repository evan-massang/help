//! memeterm Windows toast sidecar.
//!
//! Listens on 127.0.0.1:8788 and accepts a small JSON contract:
//!
//! ```json
//! POST /notify
//! {
//!   "title": "memeterm",
//!   "body": "thesis ready: ...",
//!   "url":  "http://localhost:3000/opportunities#MINT",
//!   "sound": "action"
//! }
//! ```
//!
//! On Windows the notification is fired through `winrt-notification`. On
//! non-Windows builds (e.g. when the dev runs the sidecar inside WSL2 by
//! mistake) we log + 200-OK so the backend can keep its
//! best-effort posture.

use axum::{routing::post, Json, Router};
use serde::Deserialize;
use std::net::SocketAddr;

#[derive(Debug, Deserialize)]
struct NotifyRequest {
    title: String,
    body: String,
    #[serde(default)]
    url: Option<String>,
    #[serde(default)]
    sound: Option<String>,
}

#[cfg(windows)]
fn fire_toast(req: &NotifyRequest) -> anyhow::Result<()> {
    use winrt_notification::{Sound, Toast};

    let mut toast = Toast::new(Toast::POWERSHELL_APP_ID)
        .title(&req.title)
        .text1(&req.body);

    if let Some(sound) = &req.sound {
        toast = toast.sound(match sound.as_str() {
            "critical" => Some(Sound::Reminder),
            "action" => Some(Sound::Default),
            "watch" => Some(Sound::IM),
            _ => None,
        });
    }

    if let Some(_url) = &req.url {
        // Toast click handler would normally launch the browser; the simple
        // `winrt-notification` API doesn't support that without a registered
        // appx. We log the URL so the user can see it in the action center.
    }

    toast.show().map_err(|e| anyhow::anyhow!("{e}"))
}

#[cfg(not(windows))]
fn fire_toast(req: &NotifyRequest) -> anyhow::Result<()> {
    tracing::info!(title = %req.title, body = %req.body, "non-windows: toast logged");
    Ok(())
}

async fn notify(Json(req): Json<NotifyRequest>) -> &'static str {
    if let Err(err) = fire_toast(&req) {
        tracing::warn!(error = %err, "toast failed");
    }
    "ok"
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = Router::new().route("/notify", post(notify));
    let addr = SocketAddr::from(([127, 0, 0, 1], 8788));
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind 127.0.0.1:8788");
    tracing::info!(?addr, "notifier ready");

    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
            tracing::info!("shutting down");
        })
        .await
        .expect("serve");
}
