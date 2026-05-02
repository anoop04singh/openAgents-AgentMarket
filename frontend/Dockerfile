FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
ARG VITE_RPC_URL
ARG VITE_REGISTRY_ADDR
ARG VITE_FACTORY_ADDR
ARG VITE_RESOLVER_ADDR
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
