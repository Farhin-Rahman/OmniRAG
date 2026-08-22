# OmniRAG Frontend Dockerfile
# Multi-stage build for optimal production images

# Development stage
FROM node:18-alpine as development

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Expose Vite dev server port (configured in vite.config.ts)
EXPOSE 8000

# Start development server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


# Build stage
FROM node:18-alpine as build

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy source code
COPY . .

# Get git SHA and build time for version stamp (passed as build args)
ARG BUILD_SHA=unknown
ARG BUILD_TIME=unknown
ENV VITE_BUILD_SHA=$BUILD_SHA
ENV VITE_BUILD_TIME=$BUILD_TIME

# Build for production
RUN npm run build


# Production stage
FROM nginx:alpine as production

# Copy built assets from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]

