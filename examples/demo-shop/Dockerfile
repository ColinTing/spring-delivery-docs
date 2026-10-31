FROM eclipse-temurin:8-jre
COPY target/demo-shop-1.3.0.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java","-Xms512m","-Xmx1g","-jar","/app/app.jar","--spring.profiles.active=prod"]
