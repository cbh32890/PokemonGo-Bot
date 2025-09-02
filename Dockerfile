# To build a docker container for the "master" branch (this is the default) execute:
#
# docker build --build-arg BUILD_BRANCH=master .
# (or)
# docker build .
#
# To build a docker container for the "dev" branch execute:
# 
# docker build --build-arg BUILD_BRANCH=dev .
# 
# You can also build from different fork and specify a particular commit as the branch
# 
# docker build --build-arg BUILD_REPO=YourFork/PokemonGo-Bot --build-arg BUILD_BRANCH=6a4580f .

FROM python:3.12-alpine3.22

ARG BUILD_REPO=cbh32890/PokemonGo-Bot
ARG BUILD_BRANCH=master

LABEL build_repo=$BUILD_REPO build_branch=$BUILD_BRANCH

WORKDIR /usr/src/app
VOLUME ["/usr/src/app/configs", "/usr/src/app/web"]

RUN apk -U --no-cache add python3 py3-pip tzdata \
    && rm -rf /var/cache/apk/* \
    && find / -name '*.pyc' -o -name '*.pyo' | xargs -rn1 rm -f

COPY requirements.txt .

#Need to load cert for WGET
RUN apk update
RUN apk add ca-certificates wget
RUN update-ca-certificates

RUN apk -U --no-cache add --virtual .build-dependencies python3-dev gcc g++ make musl-dev git gfortran openblas-dev libffi-dev openssl-dev
RUN ln -s locale.h /usr/include/xlocale.h
RUN python3 -m venv /usr/src/app/venv
RUN /usr/src/app/venv/bin/python3 -m ensurepip --upgrade
RUN /usr/src/app/venv/bin/pip install --no-cache-dir --upgrade pip
RUN /usr/src/app/venv/bin/pip install --no-cache-dir -r requirements.txt
RUN apk del .build-dependencies
RUN rm -rf /var/cache/apk/* /usr/include/xlocale.h
RUN find / -name '*.pyc' -o -name '*.pyo' | xargs -rn1 rm -f


ADD https://api.github.com/repos/$BUILD_REPO/commits/$BUILD_BRANCH /tmp/pgobot-version
RUN apk -U --no-cache add --virtual .pgobot-dependencies wget ca-certificates tar jq \
    && wget -q -O- https://github.com/$BUILD_REPO/archive/$BUILD_BRANCH.tar.gz | tar zxf - --strip-components=1 -C /usr/src/app \
    && jq -r .sha /tmp/pgobot-version > /usr/src/app/version \
    && apk del .pgobot-dependencies \
    && rm -rf /var/cache/apk/* /tmp/pgobot-version

CMD ["/usr/src/app/venv/bin/python3", "pokecli.py"]
