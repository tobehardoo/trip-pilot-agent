FROM node:24-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.30.3 --activate
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web ./
ARG VITE_AMAP_WEB_JS_KEY=""
ARG VITE_AMAP_SECURITY_CODE=""
RUN pnpm build

FROM nginx:1.29-alpine
ENV NGINX_ENVSUBST_FILTER=TRUSTED_PROXY_CIDR
COPY apps/web/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
