FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY pom.xml ./
COPY apps/travel-server/pom.xml apps/travel-server/pom.xml
RUN mvn --batch-mode -pl apps/travel-server dependency:go-offline
COPY apps/travel-server/src apps/travel-server/src
RUN mvn --batch-mode -pl apps/travel-server -DskipTests package

FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system trip && useradd --system --gid trip --home /app trip
WORKDIR /app
COPY --from=build /workspace/apps/travel-server/target/travel-server-*.jar app.jar
USER trip
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
