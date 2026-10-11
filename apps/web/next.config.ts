import type { NextConfig } from "next";
const config: NextConfig = {
  poweredByHeader: false,
  // OAuth callback URLs and sender-management paths contain private values.
  logging: { incomingRequests: false },
  // The development badge overlapped the sidebar's sign-out control.
  devIndicators: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};
export default config;
