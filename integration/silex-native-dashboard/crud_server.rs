// SPDX-License-Identifier: GPL-3.0-only
//! Public synthetic test launcher, not a production server CLI.
use std::{net::Ipv4Addr, path::PathBuf};
use tokio::net::TcpListener;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err("fixed fixture arguments required".into());
    }
    let data = PathBuf::from(&args[1]);
    let assets = PathBuf::from(&args[2]);
    let ready = PathBuf::from(&args[3]);
    for path in [&data, &assets] {
        if !path.is_absolute() || path.canonicalize()? != *path || !path.is_dir() {
            return Err("fixture directory rejected".into());
        }
    }
    if !ready.is_absolute() || ready.exists() || ready.is_symlink() {
        return Err("fixture handoff rejected".into());
    }
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
    let port = listener.local_addr()?.port();
    let config = silex_server::Config {
        url: format!("http://127.0.0.1:{port}"),
        port,
        data_path: data,
        hosting_path: None,
        assets_folder: "assets".into(),
        default_website_id: "default".into(),
        dashboard_path: Some(assets.clone()),
        static_path: Some(assets),
        static_routes: Vec::new(),
    };
    let (app, observed_port) = silex_server::build_app(config).await;
    if observed_port != port {
        return Err("fixture port binding rejected".into());
    }
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let mut output = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(ready)?;
    output.write_all(format!("{{\"schema\":1,\"port\":{port}}}\n").as_bytes())?;
    output.sync_all()?;
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            terminate.recv().await;
        })
        .await?;
    Ok(())
}
