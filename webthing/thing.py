"""High-level Thing base class implementation."""

from jsonschema import validate
from jsonschema.exceptions import ValidationError

from websockets import ConnectionClosedOK
from starlette.websockets import WebSocketDisconnect

from .model import Thing as ThingModel
from .action import Rename
from .event import ThingPairingEvent, ThingPairedEvent, ThingRemovedEvent
from .value import Value
from .property import Property


class Thing:
    """A Web Thing."""

    type = []
    description = ""

    def __init__(self, id_, title, type_=[], description_=""):
        """
        Initialize the object.
        id_ -- the thing's unique ID - must be a URI
        title -- the thing's title
        type_ -- the thing's type(s)
        owners_ -- the thing's owner(s)
        description -- description of the thing
        """
        self._type = set()
        if not isinstance(type_, list):
            self._type.add(type_)
        else:
            self._type = self._type.union(set(type_))

        self._type = self._type.union(set(self.type))

        self.description = description_

        self.id = id_
        self.context = "https://iot.mozilla.org/schemas"
        self.title = title
        self.properties = {}
        self.available_actions = {}
        self.available_events = {}
        self.actions = {}
        self.events = []
        self.subscribers = {}
        self.owners = []
        self.href_prefix = ""
        self.ui_href = None
        self.add_init_action(
            {
                "title": "rename",
                "description": "rename the thing's title",
                "input": {
                    "type": "object",
                    "required": ["title", ],
                    "properties": {
                        "title": {
                            "type": "string",
                        },
                    },
                },
            },
            Rename
        )

    async def as_thing_description(self):
        """
        Return the thing state as a Thing Description.
        Returns the state as a dictionary.
        """
        maybe_thing = await ThingModel.get_or_none(uid=self.id)
        if maybe_thing:
            self.title = maybe_thing.title

        thing = {
            "id": self.id,
            "title": self.title,
            "@context": self.context,
            "properties": await self.get_property_descriptions(),
            "actions": {},
            "events": {},
            "links": [
                {"rel": "properties", "href": f"{self.href_prefix}/properties", },
                {"rel": "actions", "href": f"{self.href_prefix}/actions", },
                {"rel": "events", "href": f"{self.href_prefix}/events", },
            ],
        }

        for name, action in self.available_actions.items():
            thing["actions"][name] = action["metadata"]
            thing["actions"][name]["links"] = [
                {"rel": "action", "href": f"{self.href_prefix}/actions/{name}", },
            ]

        for name, event in self.available_events.items():
            thing["events"][name] = event["metadata"]
            thing["events"][name]["links"] = [
                {"rel": "event", "href": f"{self.href_prefix}/events/{name}", },
            ]

        if self.ui_href is not None:
            thing["links"].append(
                {"rel": "alternate", "mediaType": "text/html", "href": self.ui_href, }
            )

        if self.description:
            thing["description"] = self.description

        if self._type:
            thing["@type"] = list(self._type)

        return thing

    async def get_href(self):
        """Get this thing's href."""
        if self.href_prefix:
            return self.href_prefix

        return "/"

    async def get_ui_href(self):
        """Get the UI href."""
        return self.ui_href

    async def set_href_prefix(self, prefix):
        """
        Set the prefix of any hrefs associated with this thing.
        prefix -- the prefix
        """
        self.href_prefix = prefix

        for property_ in self.properties.values():
            await property_.set_href_prefix(prefix)

        for action_name in self.actions.keys():
            for action in self.actions[action_name]:
                await action.set_href_prefix(prefix)

    async def set_ui_href(self, href):
        """
        Set the href of this thing's custom UI.
        href -- the href
        """
        self.ui_href = href

    async def get_id(self):
        """
        Get the ID of the thing.
        Returns the ID as a string.
        """
        return self.id

    async def get_title(self):
        """
        Get the title of the thing.
        Returns the title as a string.
        """
        return self.title

    async def get_context(self):
        """
        Get the type context of the thing.
        Returns the context as a string.
        """
        return self.context

    async def get_type(self):
        """
        Get the type(s) of the thing.
        Returns the list of types.
        """
        return self.type

    async def get_description(self):
        """
        Get the description of the thing.
        Returns the description as a string.
        """
        return self.description

    async def get_property_descriptions(self):
        """
        Get the thing's properties as a dictionary.
        Returns the properties as a dictionary, i.e. name -> description.
        """
        return {
            k: await v.as_property_description() for k, v in self.properties.items()
        }

    async def get_action_descriptions(self, action_name=None):
        """
        Get the thing's actions as an array.
        action_name -- Optional action name to get descriptions for
        Returns the action descriptions.
        """
        descriptions = []

        if action_name is None:
            for name in self.actions:
                for action in self.actions[name]:
                    descriptions.append(await action.as_action_description())
        elif action_name in self.actions:
            for action in self.actions[action_name]:
                descriptions.append(await action.as_action_description())

        return descriptions

    async def get_event_descriptions(self, event_name=None):
        """
        Get the thing's events as an array.
        event_name -- Optional event name to get descriptions for
        Returns the event descriptions.
        """
        if event_name is None:
            return [await e.as_event_description() for e in self.events]
        else:
            return [
                await e.as_event_description()
                for e in self.events
                if await e.get_name() == event_name
            ]

    async def add_property(self, property_):
        """
        Add a property to this thing.
        property_ -- property to add
        """
        await property_.set_href_prefix(self.href_prefix)
        await property_.set_thing(self)
        self.properties[property_.name] = property_

    async def remove_property(self, property_):
        """
        Remove a property from this thing.
        property_ -- property to remove
        """
        if property_.name in self.properties:
            del self.properties[property_.name]

    async def find_property(self, property_name):
        """
        Find a property by name.
        property_name -- the property to find
        Returns a Property object, if found, else None.
        """
        return self.properties.get(property_name, None)

    async def get_property(self, property_name):
        """
        Get a property's value.
        property_name -- the property to get the value of
        Returns the properties value, if found, else None.
        """
        prop = await self.find_property(property_name)
        if prop:
            return await prop.get_value()

        return None

    async def get_properties(self):
        """
        Get a mapping of all properties and their values.
        Returns a dictionary of property_name -> value.
        """
        return {
            await prop.get_name(): await prop.get_value()
            for prop in self.properties.values()
        }

    async def has_property(self, property_name):
        """
        Determine whether or not this thing has a given property.
        property_name -- the property to look for
        Returns a boolean, indicating whether or not the thing has the
        property.
        """
        return property_name in self.properties

    async def set_property(self, property_name, value):
        """
        Set a property value.
        property_name -- name of the property to set
        value -- value to set
        """
        prop = await self.find_property(property_name)
        if not prop:
            return
        print(f"set {self.id}'s property {property_name} to {value}")
        await prop.set_value(value)

    async def sync_property(self, property_name, value):
        """
        Sync a property value from cloud or mqtt etc.
        property_name -- name of the property to set
        value -- value to set
        """
        prop = await self.find_property(property_name)
        if not prop:
            return
        print(f"sync {self.title}'s property {property_name} to {value}")
        await prop.set_value(value, with_action=False)

    async def get_action(self, action_name, action_id):
        """
        Get an action.
        action_name -- name of the action
        action_id -- ID of the action
        Returns the requested action if found, else None.
        """
        if action_name not in self.actions:
            return None

        for action in self.actions[action_name]:
            if action.id == action_id:
                return action

        return None

    async def add_event(self, event):
        """
        Add a new event and notify subscribers.
        event -- the event that occurred
        """
        self.events.append(event)
        await event.set_thing(self)
        await self.event_notify(event)

    async def add_available_event(self, cls, metadata):
        """
        Add an available event.
        name -- name of the event
        metadata -- event metadata, i.e. type, description, etc., as a dict
        """
        if metadata is None:
            metadata = {}

        self.available_events[cls.name] = {
            "metadata": metadata,
            "subscribers": {},
        }

    async def perform_action(self, action_name, input_=None):
        """
        Perform an action on the thing.
        action_name -- name of the action
        input_ -- any action inputs
        Returns the action that was created.
        """
        if action_name not in self.available_actions:
            return None

        action_type = self.available_actions[action_name]

        if "input" in action_type["metadata"]:
            try:
                validate(input_, action_type["metadata"]["input"])
            except ValidationError:
                return None

        action = action_type["class"](self, input_=input_)
        await action.set_href_prefix(self.href_prefix)
        await self.action_notify(action)
        self.actions[action_name].append(action)
        return action

    async def remove_action(self, action_name, action_id):
        """
        Remove an existing action.
        action_name -- name of the action
        action_id -- ID of the action
        Returns a boolean indicating the presence of the action.
        """
        action = await self.get_action(action_name, action_id)
        if action is None:
            return False

        await action.cancel()
        self.actions[action_name].remove(action)
        return True

    async def add_available_action(self, metadata, cls):
        """
        Add an available action.
        name -- name of the action, default use cls.name
        metadata -- action metadata, i.e. type, description, etc., as a dict
        cls -- class to instantiate for this action
        """
        if metadata is None:
            metadata = {}

        name = cls.name
        self.available_actions[name] = {
            "metadata": metadata,
            "class": cls,
        }
        self.actions[name] = []

    def add_init_action(self, metadata, cls):
        """
        Add an available action.
        name -- name of the action, default use cls.name
        metadata -- action metadata, i.e. type, description, etc., as a dict
        cls -- class to instantiate for this action
        """
        if metadata is None:
            metadata = {}

        name = cls.name
        self.available_actions[name] = {
            "metadata": metadata,
            "class": cls,
        }
        self.actions[name] = []

    async def add_subscriber(self, ws):
        """
        Add a new websocket subscriber.
        ws -- the websocket
        """
        if id(ws) not in self.subscribers:
            self.subscribers[id(ws)] = ws

    async def remove_subscriber(self, ws):
        """
        Remove a websocket subscriber.
        ws -- the websocket
        """
        if id(ws) in self.subscribers:
            self.subscribers.pop(id(ws))

        for name in self.available_events:
            await self.remove_event_subscriber(name, ws)

    async def add_event_subscriber(self, name, ws):
        """
        Add a new websocket subscriber to an event.
        name -- name of the event
        ws -- the websocket
        """
        if name in self.available_events:
            if id(ws) not in self.available_events[name]["subscribers"]:
                self.available_events[name]["subscribers"][id(ws)] = ws

    async def remove_event_subscriber(self, name, ws):
        """
        Remove a websocket subscriber from an event.
        name -- name of the event
        ws -- the websocket
        """
        if (
                name in self.available_events
                and id(ws) in self.available_events[name]["subscribers"]
        ):
            self.available_events[name]["subscribers"].pop(id(ws))

    async def property_notify(self, property_):
        """
        Notify all subscribers of a property change.
        property_ -- the property that changed
        """
        message = {
            "messageType": "propertyStatus",
            "data": {property_.name: await property_.get_value(), },
        }

        for subscriber in list(self.subscribers.values()):
            try:
                await subscriber.send_json(message, mode="binary")
            except (WebSocketDisconnect, ConnectionClosedOK):
                pass

    async def property_action(self, property_):
        """
        Addional action when a property change.
        property_ -- the property that changed
        """
        pass

    async def action_notify(self, action):
        """
        Notify all subscribers of an action status change.
        action -- the action whose status changed
        """
        message = {
            "messageType": "actionStatus",
            "data": await action.as_action_description(),
        }

        for subscriber in list(self.subscribers.values()):
            try:
                await subscriber.send_json(message, mode="binary")
            except (WebSocketDisconnect, ConnectionClosedOK):
                pass

    async def event_notify(self, event):
        """
        Notify all subscribers of an event.
        event -- the event that occurred
        """

        if event.name not in self.available_events:
            return

        message = {
            "messageType": "event",
            "data": await event.as_event_description(),
        }

        for subscriber in list(self.available_events[event.name]["subscribers"].values()):
            try:
                await subscriber.send_json(message, mode="binary")
            except (WebSocketDisconnect, ConnectionClosedOK):
                pass

    async def add_owner(self, owner: str):
        """
        Add a new owner.
        owner -- the owner
        """
        self.owners.append(owner)
        # await event.set_thing(self)
        # await self.event_notify(event)

    async def get_owners(self):
        """Get this thing's owner(s)."""
        return self.owners


class Server(Thing):
    type = ["Server"]
    description = "Web Thing Environment"

    def __init__(self):
        super().__init__(
            "urn:webthing:server",
            "Web Thing Environment",
        )

    async def build(self):
        await self.add_property(
            Property(
                "state",
                Value("ON"),
                metadata={
                    "@type": "ServerStateProperty",
                    "title": "State",
                    "type": "string",
                    "enum": ["ON", "OFF", "REBOOT"],
                    "description": "state of webthing server",
                },
            )
        )

        await self.add_available_event(
            ThingPairedEvent,
            {
                "description": "new thing paired",
                "type": "object",
                "required": ["@type", "id", "title"],
                "properties": {
                    "@type": {
                        "type": "array",
                    },
                    "id": {
                        "type": "string",
                    },
                    "title": {
                        "type": "string",
                    },
                },
            }
        )

        await self.add_available_event(
            ThingRemovedEvent,
            {
                "description": "device removed event",
                "type": "object",
                "required": ["id", ],
                "properties": {
                    "id": {
                        "type": "string",
                    },
                },
            }
        )

        await self.add_available_event(
            ThingPairingEvent,
            {
                "description": "thing pairing event",
                "type": "object",
                "required": ["id", ],
                "properties": {
                    "id": {
                        "type": "string",
                    },
                },
            }
        )

        return self
