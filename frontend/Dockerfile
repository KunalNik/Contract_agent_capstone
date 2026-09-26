FROM node:22-alpine AS build

WORKDIR /app

# Install exactly what package-lock.json pins
COPY package*.json ./
RUN npm ci

COPY . .

# Production: type-check + bundle, served by nginx (docker build --target production)
FROM build AS bundle
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=bundle /app/dist /usr/share/nginx/html
EXPOSE 80

# Development (default target used by docker-compose): Vite dev server with proxy
FROM build AS development
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
