/** @type {import('next').NextConfig} */
const backendUrl = (process.env.MALTEUM_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const nextConfig = {
  output: 'standalone',
  // A production verification build must not replace the running dev server's chunks.
  distDir: process.env.MALTEUM_NEXT_DIST_DIR || '.next',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
