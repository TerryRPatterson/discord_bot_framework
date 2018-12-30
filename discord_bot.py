"""
Copyright 2018 Terry Patterson

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
import discord
import asyncio
import argparse
import inspect
import re as regex
from shlex import split


class BotParser(argparse.ArgumentParser):
    """Argument Parser override to allow for help handling."""

    def error(self, message):
        """Handle bad arguments."""
        help_message = self.print_help()
        help_message += f"{self.prog}: error: {message}\n"
        raise SyntaxError(help_message)

    def _print_message(self, message, file=None):
        if message:
            if file is None:
                return message
            file.write(message)

    def print_help(self, file=None):
        """Return help for the parser."""
        return self._print_message(self.format_help(), file)


class Bot(discord.Client):
    """Discord bot."""

    def __init__(self, title, prefix, **kwargs):
        """Create variables and init the client."""
        super().__init__(**kwargs)
        self.__parser = BotParser(prog=title, allow_abbrev=True, add_help=False)
        self.__sub_parsers = self.__parser.add_subparsers(dest="command")
        self.commands = {}
        self.prefix = prefix
        self.__menus = {}
        self.__items_per_page = 5
        self.__state_regex = regex.compile("Page: ([1-9]+) List: ([a-zA-Z_]+) "
                                           "Selection: (True|False)")
        self.builtins = {
            "next": self.next,
            "back": self.back,
            "select": self.select,
            "dismiss": self.dismiss
            }
        for command_name, command in self.builtins.items():
            self.command(command, command_name)

    async def check_admin(self, command, message):
        """Check if the user has privilges to run elevated commands."""
        try:
            if command.bot_admin:
                if message.author.server_permissions.administrator:
                    return True
                else:
                    message_text = (f"{message.author.mention} that command "
                                    "requires admin privilges.")
                    await self.send_message(message.channel, message_text)
                    return False
        except AttributeError:
            return True

    async def check_owner(self, command, message):
        """Check if the user has privilges to run elevated commands."""
        try:
            if command.bot_owner:
                if message.author == discord.AppInfo.owner:
                    return True
                else:
                    message_text = (f"{message.author.mention} that command "
                                    "is only accesible to the owner of the "
                                    "bot.")
                    await self.send_message(message.channel, message_text)
                    return False
        except AttributeError:
            return True

    async def on_message(self, message):
        """Handle messages."""
        self.process_message(self, message)

    async def process_message(self, message):
        """Check messages for commands."""
        if not message.author == self.user:
            if message.content.startswith(self.prefix):
                try:
                    message_no_prefix = message.content.lstrip(self.prefix)
                    message_seperated = split(message_no_prefix)
                    list_arguments = list(message_seperated)
                    parsed_args = self.__parser.parse_args(args=list_arguments)
                    command_name = parsed_args.command
                    if command_name in self.commands:
                        command = self.commands[command_name]
                        if (await self.check_admin(command, message) and
                                await self.check_owner(command, message)):
                            await command(message, parsed_args)
                except SyntaxError as error_message:
                    user = message.author
                    await self.send_message(user, error_message)

    def admin(self, command):
        """Set a method as admin only."""
        command.bot_admin = True
        return command

    def owner_only(self, command):
        """Set method to be owner only."""
        command.bot_owner = True
        return command

    def command(self, command, name=None):
        """Take in a command then create a sub_parser, and wrapped command."""
        name = self.__parse_parameters(command, name)

        def wrapped_command(message, parsed_args):
            del parsed_args.command
            dict_args = vars(parsed_args)
            return command(message, **dict_args)

        if hasattr(command, "bot_admin"):
            wrapped_command.bot_admin = True
        if hasattr(command, "bot_owner"):
            wrapped_command.bot_owner = True

        self.commands[name] = wrapped_command
        return wrapped_command

    def __parse_parameters(self, command, name=None):
        """Register parameters with argparse."""
        if inspect.isfunction(command) or inspect.ismethod(command):
            members = dict(inspect.getmembers(command))
            parameters = inspect.signature(command).parameters
            if not name:
                name = members["__name__"]
            help = members["__doc__"]
            new_sub_parser = self.__sub_parsers.add_parser(name, help=help)
            for parameter_name, parameter in parameters.items():
                if parameter.annotation != discord.Message:
                    if (parameter.kind ==
                            inspect.Parameter.POSITIONAL_ONLY):
                        raise SyntaxError("Parameters can not be postional "
                                          "only.")
                    elif (inspect.Parameter.POSITIONAL_OR_KEYWORD ==
                          parameter.kind or parameter.kind ==
                          inspect.Parameter.KEYWORD_ONLY):
                        self.__parse_keyword_postional(parameter,
                                                       parameter_name,
                                                       new_sub_parser)
            return name
        else:
            raise SyntaxError("Commands must be functions.")

    def __parse_keyword_postional(self, parameter, name, sub_parser):
        action = "store"
        const = None
        type = str
        if type(parameter.annotation) is bool:
            if parameter.annotation is True:
                action = "store_true"
            elif parameter.annontation is False:
                action = "store_false"
        elif type(parameter.annotation) is dict:
            action = "store_const"
            const = parameter.annotation["const"]
        elif parameter.annotation is int:
            type = int
        sub_parser.add_argument(name, action=action, const=const, type=type)

    def menu_command(self, menu_options, allow_selection=True, name=None,
                     help=None):
        """Register a command that opens a menu."""
        if allow_selection:
            return self.__register_select_menu(menu_options, name)
        else:
            self.__register_no_select_menu(menu_options, name, help)

    def __register_select_menu(self, menu_options, name=None):
        """Register a selectable menu."""
        def register_menu(command):
            allow_selection = True
            if inspect.isfunction(command):
                members = dict(inspect.getmembers(command))
                if name is None:
                    identifier = members["__name__"]
                else:
                    identifier = name
                help = members["__doc__"]
                self.__sub_parsers.add_parser(identifier, help=help)
                self.__menus[name] = {
                                        "options": menu_options,
                                        "handler": command
                                        }

                async def activate_menu(message, parsed_args):
                    embeded_menu = self.__create_embed_menu(identifier, 1,
                                                            allow_selection)
                    await self.send_message(message.channel,
                                            embed=embeded_menu)
                    await self.delete_message(message)
                self.commands[identifier] = activate_menu
                return command
        return register_menu

    def __register_no_select_menu(self, menu_options, name, help):
        """Register a display only menu."""
        self.__sub_parsers.add_parser(name, help=help)
        self.__menus[name] = {"options": menu_options}

        async def activate_menu(message, parsed_args):
            embeded_menu = self.__create_embed_menu(name, 1,
                                                    allow_selection=False)
            await self.send_message(message.channel,
                                    embed=embeded_menu)
            await self.delete_message(message)
        self.commands[name] = activate_menu

    async def __find_menu(self, message):
        title_prefix = f"{self.user.name} menu:"
        async for message in self.logs_from(message.channel, limit=50,
                                            before=message):
            if message.author == self.user:
                if len(message.embeds) == 1:
                    title = message.embeds[0]["title"]
                    if title.startswith(title_prefix):
                        footer = message.embeds[0]["footer"]["text"]
                        match = self.__state_regex.fullmatch(footer)
                        if match:
                            page = int(match.group(1))
                            list = match.group(2)
                            selection_text = match.group(3)
                            if selection_text == "True":
                                allow_selection = True
                            else:
                                allow_selection = False
                        else:
                            raise SyntaxError("Invaild footer detected.")
                    return (message, page, list, allow_selection)

    def __create_embed_menu(self, title, page, allow_selection=True):
        start = (page - 1) * self.__items_per_page
        embed_title = f"{self.user.name} menu: {title}"
        state_string = (f"Page: {page} List: {title} Selection: "
                        f"{allow_selection}")
        embed = discord.Embed(title=embed_title)
        embed.set_footer(text=state_string)
        options = self.__menus[title]["options"]
        if allow_selection:
            for index in range(start, start + self.__items_per_page):
                option = options[index]
                name = index + 1
                value = option
                embed.add_field(name=name, value=value, inline=False)
        else:
            description = ""
            for index in range(start, start + self.__items_per_page):
                option = options[index]
                description += option + "\n"
            embed.description = description
        return embed

    async def next(self, message: discord.Message):
        """Go to the next page on the nearest menu."""
        await self.page(message, 1)

    async def back(self, message: discord.Message):
        """Go to the next page on the nearest menu."""
        await self.page(message, -1)

    async def page(self, message: discord.Message, number_of_pages):
        """Move some number of pages."""
        menu, page, list, allow_selection = await self.__find_menu(message)
        next_page = page + number_of_pages
        new_embed = self.__create_embed_menu(list, next_page, allow_selection)
        await self.edit_message(menu, embed=new_embed)
        await self.delete_message(message)

    async def select(self, message: discord.Message, choice: int):
        """Select a menu option."""
        menu, page, list, allow_selection = await self.__find_menu(message)
        if not allow_selection:
            raise SyntaxError("That menu does not allow selection.")
        elif 0 <= choice < len(list):
            selection = self.__menus[list]["options"][choice]
            await self.__menus[list]["handler"](selection)
            await self.delete_messages([message, menu])

    async def dismiss(self, message: discord.Message):
        """Dismiss the nearest menu."""
        menu, page, list, allow_selection = await self.__find_menu(message)
        await self.delete_messages([menu, message])
