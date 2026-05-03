import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["10.0.0.*", "192.168.*.*", "172.16.*.*", "localhost", "127.0.0.1"],
};

export default nextConfig;
