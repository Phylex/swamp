.. _swamp-api:

The SWAMP API
=============
The SWAMP API is the description of the methods that every SWAMP object needs to implement. This is done to ensure composability between objects.
Implementing these methods is **mandatory** for the object to be compatible with the other components of the swamp system.

There are two sets of methods that may be provided by a swamp object. It may provide both sets. The first set is the set of methods associated with an *endpoint*.
An endpoint is a node that accepts configuration from the User. It needs to provide the following methods:

Endpoint Methods
----------------

1. The ``configure`` method allows users to pass in configuration that they want to set on the Device represented by the endpoint object. The user is responsible
   for sequencing the calls so that the target IC shows the desired behavior. The SWAMP API does not guarantee a specific sequence of parameter changes within
   one call of the configure method.

   .. code-block:: python
            
    def configure(config: dict[Any]) -> None:
        ...
       
   The method should perfom the following steps:
   
   1. validate the configuration
   2. generate the message sequence to configure the object
   3. pass the generated messages to the transport

   .. note::
     Generating the messages is something that is IC specific and therefore needs to be done by an IC expert.
     SWAMP provides classes that handle the scheduling and communication with the other SWAMP objects, allowing the IC expert to focus on the chip specific
     behaviour of the swamp object. It is highly recommended that these classes are used in stead of rewriting them yourself. 
     For incorporating this object into your SWAMP class see the :ref:`synchronous memory` for more details.

2. The ``receive_responses`` method allows the SWAMP system to return responses to the messages sent by an endpoint. This method should accept a list of messages
   and process them according to the specific needs of the SWAMP object.

   .. code-block:: python

    def receive_responses(responses: list[SWAMPMessage]) -> None:
        ...

   The method needs to mutate the internal state of the object in response to incoming messages. There may be a difference between the packages sent to the transport
   and the memory operations performed by the :ref:`synchronous memory`. This will require some translation which should be straight forward in most cases.

   .. note::
     This should also be left for the :ref:`synchronous memory` to handle. This class will provide a synchronous interface to submit write and read requests,
     which then takes care of sequencing them accordingly.

Transport Methods
-----------------
.. warning::
    TODO
