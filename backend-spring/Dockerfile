# Multi-stage build for Spring Boot API Gateway

# Stage 1: Build JAR with Maven
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /workspace

# Cache dependencies
COPY pom.xml .
RUN mvn dependency:go-offline -B

# Build application artifact
COPY src/ ./src/
RUN mvn clean package -DskipTests -B

# Stage 2: Minimal JRE Runtime
FROM eclipse-temurin:21-jre-jammy AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built JAR from builder stage
COPY --from=builder /workspace/target/*.jar app.jar

ENV JAVA_OPTS="-Xms256m -Xmx512m"
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/actuator/health || exit 1

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
