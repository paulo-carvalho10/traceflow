import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Gera um servidor enxuto em .next/standalone, só com os arquivos que ele usa:
  // é o que vai para a imagem Docker. Na Vercel, esta opção é ignorada.
  output: "standalone",
  poweredByHeader: false, // não anuncia "X-Powered-By: Next.js" em toda resposta
};

export default nextConfig;
