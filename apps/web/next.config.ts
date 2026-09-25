import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone", // minimal self-contained server for the Docker image
  poweredByHeader: false,
};

export default nextConfig;
