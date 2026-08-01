# Frontend
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm install

# Copy source
COPY . .

# Build
RUN npm run build

# Production stage — pin a specific patch release instead of floating "alpine".
FROM nginx:1.27.4-alpine

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Run nginx as the unprivileged nginx user: pre-create the pid file and make
# the html/cache paths writable, since a non-root master cannot create them.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/cache/nginx /usr/share/nginx/html /var/run/nginx.pid

USER nginx

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
