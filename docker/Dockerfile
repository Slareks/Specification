FROM ubuntu:22.04


RUN apt-get update && apt-get install -y ansible
RUN apt-get update && apt-get install -y dos2unix && rm -rf /var/lib/apt/lists/*

WORKDIR /ansible

COPY . /ansible

RUN chmod +x entrypoint.sh

ENTRYPOINT ["/ansible/entrypoint.sh"]
CMD ["sleep", "infinity"]