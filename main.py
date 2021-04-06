import csv
import os
import re
import subprocess
import sys
from datetime import datetime

import click
import git
import questionary
from pydriller import RepositoryMining
from terminaltables import AsciiTable

home = os.path.expanduser("~")

@click.command()
def main():
    click.echo("Bem vindo ao gerador de artefatos!")
    repository = get_repo()
    remote = get_remote(repository)
    branch = select_branch(repository)
    user = select_user(repository)
    start_date = select_date("Digite a data inicial (DD-MM-YYY)", datetime.now())
    end_date = select_date("Digite a data final (DD-MM-YYY) *opcional", None, True)
    only_last = questionary.confirm('Somente arquivos mais recentes?').unsafe_ask()
    commits = RepositoryMining(
        repository.working_dir,
        since=start_date,
        to=end_date,
        only_authors=[user],
        only_in_branch=branch,
    ).traverse_commits()
    table_data = [
        ['Task', 'Tipo', 'Arquivo', 'Data', 'Blob', 'Hash'],
    ]
    mapping = {}
    for commit in commits:
        for modification in commit.modifications:
            data = create_modification(modification, commit, repository, remote)
            key = modification.new_path + ('' if data[0] is None else data[0])
            if only_last and key in mapping:
                old_data = table_data[mapping[key]]
                if old_data[1].type == 'ADD' and data[1].type != 'DELETE':
                    data[1] = old_data[1]
                table_data[mapping[key]] = data
            else:
                table_data.append(data)
                mapping[key] = len(table_data) - 1

    click.echo(AsciiTable(table_data).table)
    save_csv = questionary.confirm('Deseja salvar relatório como csv?').unsafe_ask()
    if save_csv:
        default_name = datetime.now().strftime('artifact_report_%Y%m%d%H%M%S.csv')
        path = questionary.path('Onde?', default=f'{home}{os.sep}{default_name}').unsafe_ask()
        with open(path, mode='w') as csv_file:
            csv_writer = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            for index, data in enumerate(table_data):
                if index == 0:
                    csv_writer.writerow(data)
                else:
                    csv_writer.writerow(list(col.type if isinstance(col, Type) else col for col in data))
    click.echo(click.style('Pronto! 😉', fg='green'))


class Type:
    types = {
        'MODIFY': click.style('MODIFY', fg="bright_blue"),
        'ADD': click.style('ADD', fg="bright_green"),
        'COPY': click.style('COPY', fg="bright_blue"),
        'RENAME': click.style('RENAME', fg="bright_blue"),
        'DELETE': click.style('DELETE', fg="bright_red"),
        'UNKNOWN': click.style('UNKNOWN', fg="red"),
    }

    def __init__(self, type):
        self.type = type

    def __str__(self):
        return self.types[self.type]


def get_repo():
    while(True):
        try:
            dir = questionary.path(
                "Informe o diretório do projeto",
                only_directories=True,
                default=f"{home}{os.sep}"
            ).unsafe_ask()
            return git.Repo(dir)
        except git.InvalidGitRepositoryError:
            click.echo("O diretório informado não é um repositório git")


def get_remote(repository):
    if len(repository.remotes) == 1:
        return repository.remotes[0].name
    remotes = list(remote.name for remote in repository.remotes)
    return questionary.select(
        "Selecione o remoto",
        remotes,
        default='origin' if 'origin' in remotes else None
    ).unsafe_ask()


def select_branch(repository):
    branch_name = questionary.select(
        "Selecine a branch",
        list(branch.name for branch in repository.branches)
    ).unsafe_ask()
    return repository.branches[branch_name]


def select_user(repository):
    current_user = repository.config_reader().get_value('user', 'name')
    raw_users = subprocess.check_output(["git", "shortlog", "-s"], cwd=repository.working_dir)\
        .decode('utf-8').strip().split("\n")
    users = list(user.split('\t')[1] for user in raw_users)
    return questionary.select(
        "Selecione um usuário",
        users,
        default=current_user if current_user in users else None
    ).unsafe_ask()


def select_date(message, default, nullable=False):
    time_format = '%d-%m-%Y'
    while(True):
        try:
            raw_date = questionary.text(
                message,
                default=default.strftime(time_format) if isinstance(default, datetime) else ''
            ).unsafe_ask()
            if raw_date == '' and nullable:
                return None
            date = datetime.strptime(raw_date, time_format)
        except ValueError:
            click.echo("A data informada é inválida")
            continue
        if date > datetime.now():
            click.echo("A data informada deve ser menor que hoje")
            continue
        return date


def create_modification(modification, commit, repository, remote):
    remote = repository.remotes[remote].config_reader.get('url')
    http_regex = r"(https:\/\/.*)\.git"
    ssh_regex = r".*@(.*)\:(.*)\.git"
    task_regex = r"\[(\d+)\].*"
    ssh_search = re.search(ssh_regex, remote)
    task_search = re.search(task_regex, commit.msg)
    task = None
    if ssh_search:
        url = 'https://' + ssh_search[1] + '/' + ssh_search[2]
    else:
        url = re.search(http_regex, remote)[1]
    if task_search:
        task = task_search[1]
    return [
        task,
        Type(modification.change_type.name),
        modification.new_path,
        commit.committer_date.strftime('%d-%m-%Y %H:%M:%S'),
        url + '/-/blob/' + commit.hash + '/' + modification.new_path,
        commit.hash,
    ]


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
