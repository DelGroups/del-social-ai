import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Server-side address of the API inside Docker (never exposed to the browser)
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for the Docker image
  poweredByHeader: false,
  // Same-origin API (ADR 002): the browser only talks to app.del-groups.com,
  // so the session cookie lives on the panel's own origin and no CORS is needed.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_INTERNAL_URL}/:path*` }];
  },
};

export default createNextIntlPlugin()(nextConfig);
