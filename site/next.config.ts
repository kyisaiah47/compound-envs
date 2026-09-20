import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
