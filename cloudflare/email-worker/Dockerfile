FROM node:22-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

ENTRYPOINT ["npx", "wrangler"]
CMD ["deploy"]
