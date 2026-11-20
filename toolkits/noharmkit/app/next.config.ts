import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingRoot: path.resolve(process.cwd(), "../../.."),
  outputFileTracingIncludes: { "/*": ["../../../VERSION", "../projects/demo/**/*"] },
  allowedDevOrigins: ["127.0.0.1", "[::1]", ...(process.env.NOHARM_DEV_ORIGINS?.split(",").map(origin => origin.trim()).filter(Boolean) ?? [])],
  devIndicators: { position: "bottom-left" },
  turbopack: {
    root: path.resolve(process.cwd(), "../../.."),
  },
  async redirects() {
    return [{ source: "/rubrics", destination: "/noharm/rubrics", permanent: false }];
  },
};

export default nextConfig;
