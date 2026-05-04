import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["10.0.0.*", "192.168.*.*", "172.16.*.*", "localhost", "127.0.0.1"],
  httpAgentOptions: { keepAlive: true },
  experimental: { proxyTimeout: 600_000 },
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://localhost:8042";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/mcp", destination: `${backend}/mcp` },
      { source: "/health", destination: `${backend}/health` },
    ];
  },
};

export default nextConfig;
