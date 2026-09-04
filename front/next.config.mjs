/** @type {import('next').NextConfig} */
const backendUrl = (process.env.MALTEUM_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const nextConfig = {
  output: 'standalone',
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
