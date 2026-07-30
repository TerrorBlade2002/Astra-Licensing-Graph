# Portal image: a production Vite build served by nginx. No dev server, and no
# server secret — only the public VITE_* values are baked into the bundle.
FROM node:24-alpine AS build
WORKDIR /portal

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Public configuration only. Never pass a Graph secret, an OpenAI key, a
# database URL, or a browser-session key here: build args end up in the bundle.
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_ENTRA_TENANT_ID=
ARG VITE_ENTRA_SPA_CLIENT_ID=
ARG VITE_ENTRA_API_SCOPE=
ARG VITE_APP_ENV=production
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID \
    VITE_ENTRA_SPA_CLIENT_ID=$VITE_ENTRA_SPA_CLIENT_ID \
    VITE_ENTRA_API_SCOPE=$VITE_ENTRA_API_SCOPE \
    VITE_APP_ENV=$VITE_APP_ENV

RUN npm run build

FROM nginx:1.29-alpine
ENV PORT=80
# Rendered by the nginx entrypoint so the container can listen on Railway's
# injected $PORT.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /portal/dist /usr/share/nginx/html
EXPOSE 80
