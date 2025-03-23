import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from openai import OpenAI
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from typing import List, Tuple


# Load environment variables
load_dotenv(override=True)

# Initialize clients
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LINEAR_ACCESS_TOKEN = os.getenv("LINEAR_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set up Linear GraphQL client
transport = RequestsHTTPTransport(
    url="https://api.linear.app/graphql",
    headers={"Authorization": f"Bearer {LINEAR_ACCESS_TOKEN}"},
    verify=True,  # SSL verification
    retries=3,  # Number of retries
)
linear_client = Client(transport=transport, fetch_schema_from_transport=True)

# Set up OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


class DiscordLinearBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


client = DiscordLinearBot()


async def generate_issue_content(
    messages: List[discord.Message], linear_users: List[dict]
) -> Tuple[str, str, int, str]:
    """Generate issue title, description, priority, and assignee using OpenAI.

    Args:
        messages: List of Discord messages
        linear_users: List of Linear users with their IDs and names

    Returns:
        Tuple[str, str, int, str]: (title, description, priority, assignee_id)
    """
    conversation = "\n".join(
        [f"{msg.author.display_name}: {msg.content}" for msg in messages]
    )
    users_info = "\n".join([f"- {user['displayName']}" for user in linear_users])

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=(
            prompt_messages := [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that creates Linear issue details from "
                        "Discord conversations. Create a concise title, detailed description, "
                        "and suggest a priority (1-4, where 1 is urgent and 4 is low). "
                        "If you think someone should be assigned, choose from these Linear users:\n\n"
                        f"{users_info}\n\n"
                        "Only suggest an assignee if you're confident about the match. NEVER assign someone if it's not specifically mentioned in the conversation who should take care of the issue."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Create a Linear issue based on this conversation:\n\n{conversation}\n\n"
                        f"Format:\nTITLE: <title>\nDESCRIPTION: <description>\n"
                        f'PRIORITY: <1-4>\nASSIGNEE: <exact Linear username or "unassigned" if not clearly mentioned in the conversation who should be assigned>'
                    ),
                },
            ]
        ),
    )

    print("--------------------------------")
    print(f"Prompt: {prompt_messages}")
    print("--------------------------------")
    print(f"Response: {response}")
    print("--------------------------------")

    content = response.choices[0].message.content
    parts = content.split("\n")

    title = ""
    description = ""
    priority = 0
    assignee = ""

    for part in parts:
        if part.startswith("TITLE:"):
            title = part.replace("TITLE:", "").strip()
        elif part.startswith("DESCRIPTION:"):
            description = part.replace("DESCRIPTION:", "").strip()
        elif part.startswith("PRIORITY:"):
            try:
                priority = int(part.replace("PRIORITY:", "").strip())
            except ValueError:
                priority = 0
        elif part.startswith("ASSIGNEE:"):
            assignee = part.replace("ASSIGNEE:", "").strip()

    # Find the user ID if an assignee was suggested
    assignee_id = None
    if assignee:
        for user in linear_users:
            if (
                user["name"] == assignee or user["displayName"] == assignee
            ):  # Exact match only
                assignee_id = user["id"]
                break

    return title, description, priority, assignee_id


async def get_team_and_todo_state() -> Tuple[str, str]:
    """Query Linear API for team ID and Todo state ID.

    Returns:
        Tuple[str, str]: (team_id, todo_state_id)

    Raises:
        Exception: If no teams found or other API errors
    """
    query = gql(
        """
        query {
            teams {
                nodes {
                    id
                    states {
                        nodes {
                            id
                            name
                        }
                    }
                }
            }
        }
    """
    )

    result = linear_client.execute(query)
    teams = result["teams"]["nodes"]

    if not teams:
        raise Exception("No Linear teams found.")

    team_id = teams[0]["id"]

    # Find the Todo state
    todo_state_id = None
    for state in teams[0]["states"]["nodes"]:
        if state["name"].lower() == "todo":
            todo_state_id = state["id"]
            break

    return team_id, todo_state_id


async def create_linear_issue(
    title: str,
    description: str,
    priority: int = 0,
    assignee_id: str = None,
    message_url: str = None,
) -> dict:
    """Create a Linear issue with the given details."""
    try:
        # Get team and todo state IDs
        team_id, todo_state_id = await get_team_and_todo_state()

        # Add Discord message link to description
        full_description = f"{description}\n\n---\n[View Discord thread]({message_url})"

        # Create the issue
        mutation = gql(
            """
            mutation CreateIssue(
                $title: String!, 
                $description: String!, 
                $teamId: String!,
                $priority: Int,
                $assigneeId: String,
                $stateId: String
            ) {
                issueCreate(input: {
                    title: $title,
                    description: $description,
                    teamId: $teamId,
                    priority: $priority,
                    assigneeId: $assigneeId,
                    stateId: $stateId
                }) {
                    success
                    issue {
                        id
                        url
                    }
                }
            }
        """
        )

        variables = {
            "title": title,
            "description": full_description,
            "teamId": team_id,
            "priority": priority if priority in [1, 2, 3, 4] else None,
            "assigneeId": assignee_id,
            "stateId": todo_state_id,
        }

        result = linear_client.execute(mutation, variable_values=variables)

        if result["issueCreate"]["success"]:
            return {
                "success": True,
                "url": result["issueCreate"]["issue"]["url"],
                "title": title,
                "priority": priority if priority in [1, 2, 3, 4] else "default",
            }
        else:
            return {"success": False, "error": "Failed to create Linear issue."}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def collect_messages(channel: discord.abc.Messageable) -> List[discord.Message]:
    """Collect relevant messages from a channel or thread.

    Args:
        channel: Discord channel or thread to collect messages from

    Returns:
        List[discord.Message]: List of collected messages in chronological order
    """
    messages = []

    MAX_MESSAGES = 10

    # Get rest of the messages
    async for message in channel.history(limit=MAX_MESSAGES + 1):
        if message.content and not message.content.startswith("/"):
            messages.insert(0, message)

    if len(messages) > MAX_MESSAGES:
        messages = messages[-MAX_MESSAGES:]
    elif isinstance(channel, discord.Thread):
        # If this is a thread and there are less than MAX_MESSAGES, get the starter message
        starter_message = await channel.parent.fetch_message(channel.id)
        if starter_message.content and not starter_message.content.startswith("/"):
            messages.insert(0, starter_message)

    return messages


@client.tree.command(
    name="autoissue", description="Create a Linear issue from recent messages"
)
async def autoissue(interaction: discord.Interaction):
    await interaction.response.defer()

    # Fetch Linear users first
    query = gql(
        """
        query {
            users {
                nodes {
                    id
                    name
                    displayName
                }
            }
        }
        """
    )
    result = linear_client.execute(query)
    linear_users = result["users"]["nodes"]

    messages = await collect_messages(interaction.channel)

    if not messages:
        await interaction.followup.send(
            "No recent messages found to create an issue from."
        )
        return

    try:
        # Generate issue details with Linear users context
        title, description, priority, assignee_id = await generate_issue_content(
            messages, linear_users
        )

        # Create Discord message URL
        message_url = f"discord://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}/{interaction.id}"

        # Create the issue with message URL
        result = await create_linear_issue(
            title, description, priority, assignee_id, message_url
        )

        if result["success"]:
            # Find assignee name for the message
            assignee_name = "-/-"
            if assignee_id:
                for user in linear_users:
                    if user["id"] == assignee_id:
                        assignee_name = user["displayName"] or user["name"]
                        break

            # Convert priority number to text
            priority_text = {1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}.get(
                result["priority"], "None"
            )

            # Create and send an embed with Linear's purple color
            embed = discord.Embed(
                title=result["title"], url=result["url"], color=0x823FD7
            )
            embed.add_field(name="Priority", value=priority_text, inline=True)
            embed.add_field(name="Assignee", value=assignee_name, inline=True)

            await interaction.followup.send(embed=embed)
        else:
            error_embed = discord.Embed(
                title="❌ Error Creating Issue",
                description=result["error"],
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=error_embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Error Creating Issue",
            description=str(e),
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=error_embed)


client.run(DISCORD_TOKEN)
