import type { NextConfig } from "next";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Browser calls /api/* ; Next forwards to the FastAPI backend (no CORS needed).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/:path*` }];
  },
};

export default nextConfig;
