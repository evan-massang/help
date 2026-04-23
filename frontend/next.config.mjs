/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxy /api/* to the Python backend so the frontend can just call
    // relative URLs in dev and prod (all same-origin from the browser).
    const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8787";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/ws", destination: `${backend}/ws` },
    ];
  },
};

export default nextConfig;
